"""Scientific identity and leakage invariants for TESS candidate preparation."""
import unittest

import numpy as np
import pandas as pd

from scripts.data.tess_selection import choose_pilot, grouped_splits, select_candidates


def candidate(tic, toi=None, disposition="CP", ra=None, dec=0., **updates):
    row = {"tid": str(tic), "toi": toi or f"{tic}.01", "tfopwg_disp": disposition,
           "pl_orbper": 3., "pl_tranmid": 2459000., "pl_trandurh": 2.,
           "ra": float(tic) if ra is None else ra, "dec": dec}
    row.update(updates)
    return row


def references():
    return (pd.DataFrame({"kepid": [800, 900], "ra": [200., 250.], "dec": [0., 0.]}),
            pd.DataFrame({"kepid": [800]}))


def select(rows, products=None, kepler=None, **kwargs):
    catalog = pd.DataFrame(rows)
    if products is None:
        products = pd.DataFrame({"tic_id": catalog.tid.unique()})
    return select_candidates(catalog, products, *(references() if kepler is None else kepler), **kwargs)


def split_manifest(n_per_class=20, mixed_groups=0):
    rows = []
    for label in (0, 1):
        for number in range(n_per_class):
            tic = 1000 + 100 * label + number
            rows.append({"candidate_id": f"TOI-{tic}.01", "tic_id": tic,
                         "y": label, "split_group": f"TIC-{tic}"})
    for number in range(mixed_groups):
        for companion in (0, 1):
            # Also exercise a proximity group containing distinct TICs.
            tic = 2000 + 2 * number + companion
            rows.append({"candidate_id": f"TOI-{tic}.01", "tic_id": tic,
                         "y": companion, "split_group": f"TIC-{2000 + 2 * number}"})
    return pd.DataFrame(rows)


class TessCandidateSelectionTests(unittest.TestCase):
    def test_labels_belong_to_candidates_and_unknown_companions_remain_in_audit(self):
        rows = [candidate(1, "1234567.0100", "CP"), candidate(1, "1234567.0200", "PC"),
                candidate(2, disposition=" KP "), candidate(3, disposition="FP"),
                candidate(4, disposition="FA"), candidate(5, disposition="APC")]
        catalog = pd.DataFrame(rows)
        products = pd.DataFrame({"tic_id": [1, 2, 3, 4, 5]})
        kepler_catalog, kepler_manifest = references()
        inputs = [catalog, products, kepler_catalog, kepler_manifest]
        originals = [frame.copy(deep=True) for frame in inputs]
        selected, audit, overlap = select_candidates(*inputs)
        self.assertEqual(list(selected.y), [1, 1, 0, 0])
        self.assertEqual(selected.iloc[0].candidate_id, "TOI-1234567.0100")
        self.assertEqual(selected.iloc[0].tic_id, 1)
        self.assertNotIn("kepid", selected.columns)
        self.assertEqual(len(audit), len(rows))
        companion = audit.set_index("candidate_id").loc["TOI-1234567.0200"]
        self.assertTrue(pd.isna(companion.y))
        self.assertEqual(companion.pl_orbper, 3.)
        self.assertEqual(companion.reason, "unlabeled_disposition")
        self.assertEqual(companion.status, "excluded")
        self.assertTrue(overlap.empty)
        for original, current in zip(originals, inputs):
            pd.testing.assert_frame_equal(original, current)

    def test_spherical_quarantine_handles_ra_wrap_and_poles_for_all_processed_stars(self):
        rows = [candidate(1, ra=.0001), candidate(2, ra=180, dec=89.9998),
                candidate(3, ra=250), candidate(4, ra=180, dec=0)]
        catalog = pd.DataFrame({"kepid": [800, 801, 900],
                                "ra": [359.9999, 0, 250], "dec": [0, 89.9998, 0]})
        manifest = pd.DataFrame({"kepid": [800, 801, 800], "y": [0, 1, 1]})
        selected, audit, overlap = select(rows, kepler=(catalog, manifest))
        self.assertEqual(set(selected.tic_id), {3, 4})
        self.assertEqual(set(zip(overlap.tic_id, overlap.kepid)), {(1, 800), (2, 801)})
        self.assertTrue((overlap.separation_arcsec < 2.).all())
        self.assertEqual(audit.iloc[0].status, "quarantined")
        self.assertEqual(audit.iloc[1].reason, "kepler_proximity_quarantine")

    def test_quarantine_applies_to_entire_tic_and_missing_tess_coordinates(self):
        rows = [candidate(1, "1.01", ra=10), candidate(1, "1.02", "PC", ra=200),
                candidate(2, "2.01", ra=20), candidate(2, "2.02", ra=np.nan),
                candidate(3, ra=30, dec=91)]
        selected, audit, overlap = select(rows)
        self.assertTrue(selected.empty)
        self.assertEqual(set(audit.status), {"quarantined"})
        self.assertEqual(set(overlap.tic_id), {1})
        self.assertIn("missing_or_invalid_coordinates", audit.iloc[2].reason)

    def test_missing_any_processed_kepler_star_coordinate_fails_closed(self):
        for catalog in (pd.DataFrame({"kepid": [800], "ra": [np.nan], "dec": [0]}),
                        pd.DataFrame({"kepid": [900], "ra": [250.], "dec": [0]})):
            with self.subTest(catalog=catalog.to_dict()):
                with self.assertRaisesRegex(ValueError, "missing valid coordinates.*processed Kepler"):
                    select([candidate(1)], kepler=(catalog, pd.DataFrame({"kepid": [800]})))

    def test_identifier_normalization_never_rounds_integers_in_the_presence_of_missing_rows(self):
        large_id = 2 ** 53 + 1
        rows = [candidate(large_id, ra=10), candidate(2, tid="invalid")]
        selected, audit, _ = select(rows, products=pd.DataFrame({"tic_id": [str(large_id), "bad"]}))
        self.assertEqual(selected.tic_id.item(), large_id)
        self.assertEqual(selected.split_group.item(), f"TIC-{large_id}")
        self.assertTrue(pd.isna(audit.iloc[1].tic_id))

    def test_companions_and_unlabeled_sky_bridges_share_connected_group(self):
        # 1--2--3 are connected at 4 arcsec intervals; endpoints are >5 arcsec apart.
        rows = [candidate(1, "1.01", ra=10), candidate(1, "1.02", "FP", ra=10),
                candidate(2, disposition="PC", ra=10 + 4 / 3600),
                candidate(3, disposition="FP", ra=10 + 8 / 3600), candidate(4, ra=20)]
        products = pd.DataFrame({"tic_id": [1, 3, 4]})
        selected, audit, _ = select(rows, products=products)
        self.assertEqual(set(selected.loc[selected.tic_id.isin([1, 3]), "split_group"]), {"TIC-1"})
        self.assertEqual(audit.loc[audit.tic_id == 2, "split_group"].item(), "TIC-1")
        self.assertEqual(selected.loc[selected.tic_id == 4, "split_group"].item(), "TIC-4")

    def test_ephemerides_bounds_product_coverage_and_bad_identifiers_are_audited(self):
        rows = [candidate(1, pl_orbper=.5, pl_trandurh=.1),
                candidate(2, pl_orbper=30, pl_trandurh=20),
                candidate(3, pl_orbper=30.1), candidate(4, pl_trandurh=20.1),
                candidate(5, pl_tranmid=1900), candidate(6, pl_orbper=np.nan),
                candidate(7), candidate(8, pl_orbper=.5, pl_trandurh=12),
                candidate(9, tid="9.5"), candidate(10, toi="bad"),
                candidate(11, toi="11.01"), candidate(12, toi="11.01")]
        selected, audit, _ = select(rows, products=pd.DataFrame({"tic_id": list(range(1, 13))[:6] + list(range(8, 13))}))
        self.assertEqual(set(selected.tic_id), {1, 2})
        reasons = list(audit.reason)
        self.assertIn("period_out_of_range", reasons[2])
        self.assertIn("duration_out_of_range", reasons[3])
        self.assertIn("invalid_ephemeris", reasons[4])
        self.assertIn("invalid_ephemeris", reasons[5])
        self.assertIn("no_manifest_lightcurve", reasons[6])
        self.assertIn("duration_not_shorter_than_period", reasons[7])
        self.assertIn("invalid_tic_id", reasons[8])
        self.assertIn("invalid_candidate_id", reasons[9])
        self.assertIn("duplicate_candidate_id", reasons[10])
        self.assertIn("duplicate_candidate_id", reasons[11])


class TessGroupedSplitTests(unittest.TestCase):
    def assert_partition(self, manifest, splits, forced=()):
        all_indices = np.concatenate(list(splits.values()))
        np.testing.assert_array_equal(np.sort(all_indices), np.arange(len(manifest)))
        seen_stars, seen_groups = set(), set()
        for indices in splits.values():
            rows = manifest.iloc[indices]
            self.assertEqual(set(rows.y), {0, 1})
            self.assertFalse(seen_stars & set(rows.tic_id))
            self.assertFalse(seen_groups & set(rows.split_group))
            seen_stars.update(rows.tic_id)
            seen_groups.update(rows.split_group)
        self.assertTrue(set(forced) <= set(manifest.iloc[splits["train_idx"]].split_group))

    def test_fixed_stratification_is_deterministic_group_disjoint_and_both_classes(self):
        manifest = split_manifest(mixed_groups=6)
        # Multiple candidates with the same TIC must also remain together.
        extra = manifest.iloc[[0]].copy()
        extra["candidate_id"] = "TOI-1000.02"
        manifest = pd.concat([manifest, extra], ignore_index=True)
        original = manifest.copy(deep=True)
        splits = grouped_splits(manifest)
        repeated = grouped_splits(manifest)
        self.assert_partition(manifest, splits)
        for name in splits:
            np.testing.assert_array_equal(splits[name], repeated[name])
        shuffled = manifest.sample(frac=1, random_state=11).reset_index(drop=True)
        shuffled_splits = grouped_splits(shuffled)
        for name in splits:
            self.assertEqual(set(manifest.iloc[splits[name]].candidate_id),
                             set(shuffled.iloc[shuffled_splits[name]].candidate_id))
        pd.testing.assert_frame_equal(manifest, original)

    def test_pilot_balances_available_classes_and_retains_complete_proximity_groups(self):
        manifest = split_manifest(n_per_class=15, mixed_groups=4)
        # Make every pure group contain two candidates so an odd target exceeds n.
        extra = manifest.loc[manifest.tic_id < 2000].copy()
        extra["candidate_id"] = extra.candidate_id.str.replace(".01", ".02", regex=False)
        manifest = pd.concat([manifest, extra], ignore_index=True)
        pilot = choose_pilot(manifest, 13, 42)
        self.assertGreaterEqual(len(pilot), 13)
        self.assertLessEqual(len(pilot), 16)
        self.assertLessEqual(abs((pilot.y == 0).sum() - (pilot.y == 1).sum()), 2)
        for group in pilot.split_group.unique():
            self.assertEqual(set(pilot.loc[pilot.split_group == group, "candidate_id"]),
                             set(manifest.loc[manifest.split_group == group, "candidate_id"]))
        pd.testing.assert_frame_equal(pilot, choose_pilot(manifest.sample(frac=1, random_state=4), 13, 42))
        scarce = split_manifest(n_per_class=1, mixed_groups=0)
        pd.testing.assert_frame_equal(choose_pilot(scarce, 100, 42), scarce.sort_values("candidate_id").reset_index(drop=True))

    def test_inspected_pilot_groups_are_training_only_with_original_fraction_targets(self):
        manifest = split_manifest(n_per_class=30, mixed_groups=6)
        pilot = choose_pilot(manifest, 12, 4)
        forced = set(pilot.split_group)
        splits = grouped_splits(manifest, train_only_groups=forced)
        self.assert_partition(manifest, splits, forced)
        all_groups = manifest.split_group.nunique()
        for name in ("val_idx", "test_idx"):
            self.assertEqual(manifest.iloc[splits[name]].split_group.nunique(), int(np.ceil(.15 * all_groups)))
        with self.assertRaisesRegex(ValueError, "Too few groups"):
            grouped_splits(manifest, train_only_groups=manifest.split_group)
        with self.assertRaisesRegex(ValueError, "absent from the manifest"):
            grouped_splits(manifest, train_only_groups=["TIC-missing"])

    def test_single_fixed_group_shuffle_fallback_and_infeasible_classes(self):
        # A singleton pure signature prevents three-way stratification, while all
        # other groups contain both labels, making any >=2-group holdout valid.
        manifest = split_manifest(n_per_class=0, mixed_groups=9)
        pure = split_manifest(n_per_class=1).iloc[[0]]
        manifest = pd.concat([manifest, pure], ignore_index=True)
        self.assert_partition(manifest, grouped_splits(manifest))
        impossible = split_manifest(n_per_class=5)
        impossible.loc[impossible.y == 1, "split_group"] = "TIC-one-positive-group"
        with self.assertRaisesRegex(ValueError, "lacks both classes.*do not search random seeds"):
            grouped_splits(impossible)

    def test_a_single_tic_cannot_be_assigned_inconsistent_groups(self):
        manifest = split_manifest()
        manifest.loc[1, "tic_id"] = manifest.loc[0, "tic_id"]
        with self.assertRaisesRegex(ValueError, "TIC appears in multiple split groups"):
            grouped_splits(manifest)


if __name__ == "__main__":
    unittest.main()
