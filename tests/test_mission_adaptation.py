"""Actual gradients, protected groups, calibration and resumable training checks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import torch
from torch import nn

from scripts.experiments.adaptation_data import INPUTS, MissionBatchPlan, audit_partitions, make_roles
from scripts.experiments.adaptation_metrics import choose_thresholds, fit_temperature, metrics, paired_group_bootstrap
from scripts.experiments.mission_adaptation import run_suite, validate_config
from training.cnn.mission_adaptation import MissionAdaptationCNN, reverse_gradient, reversal_schedule
from training.cnn.train_kepler_cnn import ExoMinerStyleCNN


def synthetic_data():
    generator = torch.Generator().manual_seed(101)
    data = {}
    for mission in ("kepler", "tess"):
        data[mission] = {}
        for role, n in (("train", 12), ("selection", 8), ("calibration", 8), ("audit", 8)):
            x = [torch.randn((n, *shape), generator=generator) for shape in ((200,3),(100,3),(7,),(907,))]
            data[mission][role] = {**dict(zip(INPUTS, x)), "y": torch.arange(n).remainder(2).float(),
                "metadata": [{"candidate_id": f"{mission}-{role}-{i}", "split_group": f"{mission}-{role}-{i//2}",
                              "star_id": i//2+1, "period": float(i+5), "epoch_bjd": 2457000.,
                              "duration_hours": 2.} for i in range(n)]}
    return data


class MissionModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def test_reversal_sign_scale_and_head_gradient(self):
        x = torch.tensor([[1., 2.], [3., 4.]], requires_grad=True)
        head = nn.Linear(2, 1, bias=False)
        with torch.no_grad():
            head.weight.fill_(2.)
        head(reverse_gradient(x, .3)).sum().backward()
        torch.testing.assert_close(x.grad, torch.full_like(x, -.6))
        torch.testing.assert_close(head.weight.grad, torch.tensor([[4., 6.]]))
        x.grad = None
        head.zero_grad()
        head(reverse_gradient(x, 0.)).sum().backward()
        torch.testing.assert_close(x.grad, torch.zeros_like(x))
        self.assertGreater(float(head.weight.grad.abs().sum()), 0.)
        with self.assertRaises(ValueError):
            reverse_gradient(x, float("nan"))

    def test_retained_encoder_logits_and_shape_contract(self):
        reference = ExoMinerStyleCNN(scalar_features=7, flat_features=907, dropout=.2,
            scalar_dropout=.1, wide_dropout=.15, use_wide_branch=False)
        model = MissionAdaptationCNN()
        model.load_state_dict(reference.state_dict(), strict=True)
        reference.eval(); model.eval()
        part = synthetic_data()["tess"]["selection"]
        x = [part[k][:2] for k in INPUTS]
        with torch.inference_mode():
            torch.testing.assert_close(model(*x), reference(*x), rtol=0, atol=0)
            self.assertEqual(tuple(model.encode(*x).shape), (2, 576))
        with self.assertRaises(ValueError):
            model(x[0][:,:199], *x[1:])

    def test_mission_loss_reverses_encoder_and_preserves_head_direction(self):
        model = MissionAdaptationCNN(adversarial=True).eval()
        part = synthetic_data()["tess"]["selection"]
        x = [part[k][:2] for k in INPUTS]
        emb = model.encode(*x)
        normal = nn.functional.cross_entropy(model.mission_head(emb), torch.tensor([0,1]))
        normal.backward()
        encoder_grad = model.global_branch.stem.block[0].weight.grad.clone()
        head_grad = model.mission_head[0].weight.grad.clone()
        model.zero_grad()
        _, logits = model(*x, grl_strength=.4)
        nn.functional.cross_entropy(logits, torch.tensor([0,1])).backward()
        torch.testing.assert_close(model.global_branch.stem.block[0].weight.grad, -.4*encoder_grad)
        torch.testing.assert_close(model.mission_head[0].weight.grad, head_grad)
        self.assertIsNone(model.classifier[0].weight.grad)
        self.assertEqual(reversal_schedule(0, 100), 0.)
        self.assertGreater(reversal_schedule(99, 100), .99)

    def test_balanced_batches_deterministic_cycles_and_phase_switch(self):
        data = synthetic_data()
        plan = MissionBatchPlan(data, 8, 42)
        for step in range(9):
            x,y,d = plan.batch("dann", step, 3)
            self.assertEqual(d.bincount().tolist(), [4,4])
            twin = MissionBatchPlan(data, 8, 42).batch("pooled", step, 3)
            for left,right in zip(x,twin[0]):
                torch.testing.assert_close(left,right,rtol=0,atol=0)
        self.assertEqual(plan.batch("fine_tuned", 2, 3)[2].sum(), 0)
        self.assertEqual(plan.batch("fine_tuned", 3, 3)[2].sum(), 8)
        sampled = torch.cat([plan.indices("tess", step, 4) for step in range(3)])
        self.assertEqual(sorted(sampled.tolist()), list(range(12)))


class PartitionCalibrationTests(unittest.TestCase):
    def frame(self):
        rows = []
        for split in ("train", "val", "test"):
            for i in range(24):
                for candidate in range(2):
                    rows.append({"candidate_id":f"{split}-{i}-{candidate}", "star_id": len(rows)//2+1,
                                 "split_group":f"{split}-{i}", "split":split, "y":i%2})
        frame=pd.DataFrame(rows)
        return frame, {name+"_idx":np.flatnonzero(frame.split.eq(name)) for name in ("train","val","test")}

    def test_original_splits_and_inner_groups_protected(self):
        frame, splits = self.frame()
        audit_partitions(frame,splits)
        roles=make_roles(frame,2718,12)
        seen=set()
        for name,idx in roles.items():
            groups=set(frame.iloc[idx].split_group)
            self.assertFalse(groups & seen);seen |= groups
            self.assertFalse(frame.iloc[idx].split.eq("test").any())
        changed=frame.copy();changed.loc[0,"star_id"]=changed.loc[len(changed)-1,"star_id"]
        with self.assertRaises(ValueError):audit_partitions(changed,splits)
        changed=splits.copy();changed["train_idx"]=splits["test_idx"]
        with self.assertRaises(ValueError):audit_partitions(frame,changed)

    def test_calibration_can_help_or_hurt_audit_and_preserves_ranking(self):
        y=np.array([0,1,0,1,0,1,0,1]);z=np.array([-8,8,8,-8,-8,8,-8,8])
        fit=fit_temperature(y,z)
        self.assertLessEqual(fit["nll_after"],fit["nll_before"])
        raw=metrics(y,z);cal=metrics(y,z,fit["temperature"])
        self.assertAlmostEqual(raw["average_precision"],cal["average_precision"])
        self.assertAlmostEqual(raw["roc_auc"],cal["roc_auc"])
        perfect=np.array([-8,8,-8,8,-8,8,-8,8])
        self.assertGreater(metrics(y,perfect,fit["temperature"])["brier"],metrics(y,perfect)["brier"])
        self.assertEqual(sum(r["n"] for r in cal["reliability"]),len(y))

    def test_ties_unattainable_precision_and_group_intervals(self):
        y=np.array([0,1,0,1]);z=np.zeros(4)
        thresholds=choose_thresholds(y,z)
        self.assertFalse(thresholds["precision"]["attainable"])
        self.assertIsNone(thresholds["precision"]["threshold"])
        result=paired_group_bootstrap(y,["a","a","b","b"],z,z,repeats=20)
        self.assertEqual(result["percentile_95"],[0.,0.])
        self.assertEqual(metrics([1,1],[1,2])["average_precision"],None)

    def test_config_caps_are_strict(self):
        for change in ({"cpu_threads":5},{"batch_size":3},{"device":"cuda:0"},
                       {"seeds":[42,42]},{"mission_loss_weight":float("nan")},{"typo":2}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_config(change)


class TrainingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def test_five_real_training_arms_failure_resume_and_completed_dedup(self):
        data=synthetic_data()
        config=validate_config({"seeds":[42],"steps":4,"pretrain_steps":2,"eval_every":2,
                               "batch_size":4,"bootstrap_repeats":20,"max_seconds":120,"invocation_seconds":60})
        provenance={"cohort":"synthetic_training_fixture","known_ephemerides":False}
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/"resumed"
            def interrupt(arm,seed,step):
                if arm=="tess_only" and step==2:raise RuntimeError("injected interruption after durable checkpoint")
            with self.assertRaisesRegex(RuntimeError,"injected interruption"):
                run_suite(config,output,data,provenance,on_checkpoint=interrupt)
            self.assertEqual(json.loads((output/"state.json").read_text())["status"],"failed")
            run_suite(config,output,data,provenance,resume=True)
            summary=json.loads((output/"summary.json").read_text())
            self.assertEqual(len(summary["runs"]),5)
            for row in summary["runs"]:
                self.assertEqual((row["updates"],row["examples_drawn"]),(4,16))
                self.assertGreater(row["planet_parameters"],0)
                self.assertFalse(any("test" in k for k in row["audit"]))
            fine=next(r for r in summary["runs"] if r["arm"]=="fine_tuned")
            self.assertGreater(fine["best_step"],2)
            before={str(p.relative_to(output)):p.read_bytes() for p in output.rglob("*") if p.is_file()}
            self.assertTrue(run_suite(config,output,data,provenance,resume=True)["already_complete"])
            after={str(p.relative_to(output)):p.read_bytes() for p in output.rglob("*") if p.is_file()}
            self.assertEqual(before,after)
            uninterrupted=Path(temp)/"uninterrupted"
            run_suite(config,uninterrupted,data,provenance)
            for arm in config["arms"]:
                self.assertEqual(json.loads((output/f"{arm}-seed42/predictions.json").read_text()),
                                 json.loads((uninterrupted/f"{arm}-seed42/predictions.json").read_text()))
            with self.assertRaisesRegex(ValueError,"specification changed"):
                run_suite({**config,"learning_rate":.001},output,data,provenance,resume=True)
            (output/"dann-seed42/best_model.pt").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError,"corrupt"):
                run_suite(config,output,data,provenance,resume=True)

    def test_zero_domain_weight_matches_pooled_training(self):
        data=synthetic_data()
        config=validate_config({"seeds":[19],"arms":["pooled","dann"],"steps":2,"pretrain_steps":1,
            "eval_every":2,"batch_size":4,"mission_loss_weight":0.,"bootstrap_repeats":20,
            "max_seconds":60,"invocation_seconds":60})
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/"zero"
            run_suite(config,output,data,{"cohort":"synthetic_training_fixture"})
            a=json.loads((output/"pooled-seed19/predictions.json").read_text())
            b=json.loads((output/"dann-seed19/predictions.json").read_text())
            self.assertEqual(a,b)


if __name__ == "__main__":
    unittest.main()
