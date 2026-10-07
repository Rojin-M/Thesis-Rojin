window.ACADEMY_CURRICULUM = {
  "version": 2,
  "revision": "2026-09-23.1",
  "checked": "2026-09-28",
  "contentRevision": "2026-09-28.3",
  "researchExtension": {
    "checked": "2026-09-28",
    "title": "When machine learning meets the sky",
    "lead": "A model notices something. What happens next? Follow the evidence from a changing pixel to a telescope request, a planet candidate or an unusual spectrum—and learn where each claim stops.",
    "minutes": 25,
    "sourcePolicy": "Primary records opened 28 September 2026; dates below distinguish events, manuscripts and publication. Verified means the source supports the attributed claim, not that we reproduced the study. This is a curated path, not an exhaustive latest-paper survey or a common benchmark.",
    "workflows": [
      {
        "id": "btsbot",
        "title": "BTSbot-nearby · obtaining a spectrum",
        "steps": [
          [
            "Observe",
            "ZTF images reveal a changing source."
          ],
          [
            "Score",
            "BTSbot combines image and scalar information."
          ],
          [
            "Choose",
            "Nearby-galaxy context and a selection policy trigger a request."
          ],
          [
            "Measure",
            "SEDM on Palomar's 60-inch telescope takes a spectrum."
          ],
          [
            "Interpret",
            "A spectrum adds physical evidence; scientists study the event."
          ]
        ],
        "boundary": "A demonstrated observing loop: software requested a new measurement. The 2024jlf paper does not establish that every later interpretation or public report was autonomous.",
        "sources": [
          "btsbot",
          "btsbot-nearby"
        ]
      },
      {
        "id": "broker",
        "title": "Survey broker · choosing what deserves attention",
        "steps": [
          [
            "Observe",
            "Rubin compares a new image with a reference image."
          ],
          [
            "Notify",
            "A difference-image detection produces an alert packet."
          ],
          [
            "Enrich",
            "A broker adds catalog matches, features and possible classes."
          ],
          [
            "Prioritize",
            "Rules or models select alerts for a science program."
          ],
          [
            "Follow up",
            "A separate observing program must arrange and obtain new data."
          ]
        ],
        "boundary": "A broker output is a selection or classification. Telescope scheduling and a successful exposure are further steps; an alert alone is not a confirmed discovery.",
        "sources": [
          "rubin-brokers"
        ]
      },
      {
        "id": "watcher",
        "title": "Our watcher · processing archival TESS data",
        "steps": [
          [
            "Retrieve",
            "Bounded polling finds public products for selected targets."
          ],
          [
            "Search",
            "BLS proposes periodic dimming signals."
          ],
          [
            "Rank",
            "The frozen Kepler CNN supplies model_score."
          ],
          [
            "Review",
            "Saved diagnostics and comparison scores support a human dossier."
          ],
          [
            "Test",
            "Source checks and independent follow-up are needed for a planet claim."
          ]
        ],
        "boundary": "Our deployed loop acquires existing observations. It does not command a telescope. Research-only event localizers and ensembles have not replaced the authoritative scorer.",
        "sources": [],
        "project": true
      }
    ],
    "cards": [
      {
        "id": "btsbot",
        "shortTitle": "A telescope takes action",
        "title": "1. A score can trigger a real spectrum",
        "status": "Demonstrated follow-up · 2024 event / 2025 paper",
        "hook": "A young supernova changes quickly. Reducing the delay to a spectrum can preserve evidence that will soon disappear.",
        "input": "ZTF transient images and extracted features; BTSbot-nearby adds nearby-galaxy context.",
        "mechanism": "BTSbot is a multimodal CNN: an image branch and 25 scalar features help score bright transients. A selection policy uses the score and context to request SEDM spectroscopy on Palomar's 60-inch telescope. The model and the observing policy have different jobs.",
        "evidence": "For SN 2024jlf on 28 May 2024, the request was logged at 07:53:40 and observing began at 08:00:51: about seven minutes later. The spectrum was taken about 0.7 days after inferred first light. Those are two different clocks.",
        "limit": "This demonstrates autonomous follow-up for a selected transient task. Researchers performed the wider campaign and physical interpretation; automatic public reporting was future work in this paper.",
        "connection": "Our pixel/scalar experts also combine evidence, but our watcher downloads archival observations. A future follow-up policy would need resource constraints, uncertainty and an auditable decision record.",
        "sources": [
          "btsbot",
          "btsbot-nearby"
        ],
        "lessons": [
          "pixels",
          "operations"
        ],
        "related": [
          {
            "title": "The earlier autonomous chain: SN 2023tyk",
            "text": "Northwestern's 13 October 2023 account describes ZTF detection on October 3, BTSbot selection on October 5, a requested SEDM spectrum, SNIascore Type Ia classification and automated sharing on October 7. This was a linked workflow built by people, not a 2026 discovery. It is a concrete example, not an identification of an unnamed news story.",
            "sources": [
              "btsbot-2023"
            ]
          }
        ],
        "reflection": {
          "question": "Does a seven-minute response mean the star exploded seven minutes earlier?",
          "answer": "No. Request-to-observation latency measures the observing system. Time since first light requires a separate estimate from the light curve; it was about 0.7 days here."
        }
      },
      {
        "id": "brokers",
        "shortTitle": "Sort a changing sky",
        "title": "2. Brokers turn alerts into useful queues",
        "status": "Operational alert milestone · February 2026; documentation updated July 2026",
        "hook": "A million notifications are useful only if the right evidence reaches the right observer in time.",
        "input": "Difference-image alert packets: measurements of what changed relative to a reference sky image.",
        "mechanism": "A broker adds context such as catalog matches and light-curve classifications, then exposes filters or ranked selections. Rubin describes ML classification in ALeRCE and ML enrichment in Fink. Rules also matter: a science program can require a particular brightness or history before requesting scarce follow-up time.",
        "evidence": "Rubin reported 800,000 alerts on the night of 24 February 2026. Its February 25 release forecast up to seven million per night eventually; that forecast is not the measured rate that night or a verified September rate.",
        "limit": "Alerts are change notifications, not counts of unique objects or confirmed discoveries. Brokers differ; a broker classification does not prove a telescope took a spectrum. The July documentation describes roles, not a shared performance benchmark.",
        "connection": "Keep acquisition, event records, model scores and review decisions distinct in our pipeline too. A useful queue must balance missed events with review workload.",
        "sources": [
          "rubin-alerts",
          "rubin-brokers"
        ],
        "lessons": [
          "operations",
          "metrics"
        ]
      },
      {
        "id": "exominer",
        "shortTitle": "Vet a transit signal",
        "title": "3. ExoMiner++ asks whether a detected signal looks planetary",
        "status": "Published research · 2025 manuscript; NASA coverage January 2026",
        "hook": "A convincing dip can come from the wrong star. Give the model evidence about the cause, not just the shape.",
        "input": "Already detected TESS threshold-crossing events (TCEs), with light-curve and instrument diagnostics; training combines Kepler and TESS examples.",
        "mechanism": "The deep model combines views including difference images, periodograms, flux trends, unfolded flux and spacecraft information. A difference image can reveal where the changing light comes from; an instrument channel can expose a systematic that resembles a transit.",
        "evidence": "The paper reports 7,330 candidate-classified TCEs among about 148,000 unlabeled TCEs, with 50 newly introduced Community TESS Objects of Interest after further selection. NASA's January 22, 2026 article is later coverage of the 2025 work.",
        "limit": "These are not 7,330 new confirmed planets. TCEs, unique hosts and catalog candidates are different counting units. Vetting a supplied signal does not establish sensitivity to every unseen transit in raw time series.",
        "connection": "This motivates complementary pixel, variability and morphology experts and an explicit input contract. It does not show that our stack or mission-adaptation method must improve.",
        "sources": [
          "exominer",
          "exominer-nasa"
        ],
        "lessons": [
          "frontier",
          "contract",
          "pixels"
        ]
      },
      {
        "id": "transit-search",
        "shortTitle": "Search before folding",
        "title": "4. A Transformer can search without a supplied period",
        "status": "Published candidate search · MNRAS April 2025 issue",
        "hook": "If a planet crosses its star only once during the observations, there may be no reliable period to fold on.",
        "input": "Unfolded light curves extracted from TESS full-frame images, plus background and centroid time series. The network does not need an input transit ephemeris.",
        "mechanism": "Salinas and colleagues use a Transformer-inspired model to identify transit candidates in time order. Attention relates measurements across a sequence, while background and centroid changes supply clues about nonplanetary events. FFI describes the data product origin; it does not mean the network ingests every raw image pixel.",
        "evidence": "The paper reports 214 candidate systems from sectors 1–26 under its selection: 122 multi-transit, 88 single-transit and four multi-planet systems.",
        "limit": "Candidate systems are not confirmed planets. No matched fixed-control-budget comparison with our detector is established here; candidate counts do not rank architectures.",
        "connection": "Our candidate Transformer and our direct event localizer solve different tasks. To test an attention-based localizer, freeze the same inputs, host splits, injection depths and control budget as the CNN and TLS comparisons.",
        "sources": [
          "transformer"
        ],
        "lessons": [
          "attention",
          "injections"
        ],
        "reflection": {
          "question": "Why would a candidate classifier be an unfair baseline for finding an unknown single transit?",
          "answer": "A classifier may require a detected event and a period to construct its input. A search must first locate that event. Compare search with search, then evaluate vetting on the same candidate set."
        }
      },
      {
        "id": "raven",
        "shortTitle": "Model the alternatives",
        "title": "5. RAVEN separates ranking from statistical validation",
        "status": "Framework submitted 2025 · survey application published in MNRAS, March 2026",
        "hook": "A planet claim needs alternatives: could a stellar eclipse or a background system explain the data?",
        "input": "Transit candidates, simulated planets, eight astrophysical false-positive scenarios, real false positives and source-position information.",
        "mechanism": "RAVEN uses gradient-boosted and Gaussian-process classifiers with scenario priors to estimate competing explanations. Its initial framework targets SPOC candidates at 0.5–16-day periods and depths above 300 ppm; posterior and radius conditions also govern validation.",
        "evidence": "The 2026 application searched over 2.2 million magnitude-selected main-sequence stars with BLS and applied ML vetting. The authors report 118 newly statistically validated planets, including 31 newly detected in this work, alongside over 2,000 unvalidated candidates.",
        "limit": "Statistical validation is conditional on the modeled alternatives, priors and selection; the survey also manually checked highly ranked candidates. The 118 and 2,000 counts describe different evidence levels. We have not independently validated these objects.",
        "connection": "Our frozen CNN sigmoid is a ranking score, not this kind of astrophysical posterior. On-target injections do not establish background-binary rejection. Automation already exists; a contribution needs a measured advance on a defined task.",
        "sources": [
          "raven",
          "raven26"
        ],
        "lessons": [
          "probability",
          "validation"
        ]
      },
      {
        "id": "anomalies",
        "shortTitle": "Find the unusual",
        "title": "6. An unusual spectrum is an invitation to investigate",
        "status": "DESI VAE · published January 2026 / MNRAS April issue",
        "hook": "What if the interesting object has no familiar class label? Learn typical structure, then inspect what does not fit.",
        "input": "About 200,000 DESI spectra: brightness measured across wavelength rather than across time.",
        "mechanism": "A variational autoencoder compresses spectra into a small latent representation and reconstructs them. Large reconstruction residuals or unusual latent locations flag outliers. Astronomaly uses human feedback to prioritize what to inspect next.",
        "evidence": "Nicolaou and colleagues find both instrumental artifacts and physically unusual spectra. The useful product is an ordered review set and interpretable spectral differences, not a single planet-like classification score.",
        "limit": "Rare stars or quasars can reconstruct poorly when galaxies dominate training. An outlier score is neither a calibrated class probability nor proof of new astrophysics.",
        "connection": "Our self-supervised representations could support event triage, but rarity and planet evidence must stay separate. Inspect pixels and instrument channels before treating an unusual dip as a scientific discovery.",
        "sources": [
          "desi-vae"
        ],
        "lessons": [
          "representation",
          "uncertainty"
        ],
        "related": [
          {
            "title": "Dated context: learning galaxy images without morphology labels",
            "text": "Mohale and Lochner (MNRAS May 2024 issue) use BYOL to learn representations from Galaxy Zoo DECaLS images. Similar images cluster together; Astronomaly uses the features to find merger candidates. The representation objective needs no morphology labels, but physical interpretation still needs evidence. Augmentations decide which differences the model is encouraged to ignore.",
            "sources": [
              "galaxy-byol"
            ]
          }
        ]
      },
      {
        "id": "reading-claims",
        "shortTitle": "Read a headline critically",
        "title": "7. Two new preprints, two questions worth asking",
        "status": "Preprints · June and August 2026; not reproduced here",
        "hook": "Before admiring a metric, ask what counted as an example and where its truth label came from.",
        "input": "EXOVEIL predicts stellar flux with a transit-masked, self-supervised Transformer. Astro-Hunters derives seven sliding-window features per TESS cadence and compares classifiers using star-disjoint splits.",
        "mechanism": "EXOVEIL searches prediction residuals with a matched filter and vets them with XGBoost. Astro-Hunters changes the source of the training labels while holding the comparison protocol fixed. One probes a search strategy; the other probes what the benchmark actually rewards.",
        "evidence": "EXOVEIL v3 reports 47/47 selected confirmed TESS planets recovered and 179 transit-like anomalies in a separate Kepler search. Astro-Hunters v1 uses 189,279 cadences from twelve hosts; feature-derived labels give AUC 0.9915, while properly converted ephemeris labels give AUC 0.7880 and AUPRC 0.2092.",
        "limit": "Selected-planet recovery is not survey-wide completeness; 179 anomalies are not 179 confirmed planets. Cadences are not independent stars. The high feature-label AUC measures circular agreement, not independently labeled transit detection. Neither study is a head-to-head ranking against our candidate AP.",
        "connection": "Pin label provenance and time systems, split by host, and report depth-stratified recovery. Our missed 500-ppm injections motivate a fair residual-search experiment; they do not prove that another paper's system would solve the problem.",
        "sources": [
          "exoveil",
          "hunters"
        ],
        "lessons": [
          "frontier",
          "splits",
          "injections"
        ],
        "reflection": {
          "question": "Which is the useful denominator: 189,279 cadences or twelve hosts?",
          "answer": "Both, for different purposes. Cadences describe the prediction task; twelve hosts describe how few independent stellar systems support transfer to new stars. A large row count cannot replace a diverse held-out host sample."
        }
      },
      {
        "id": "next-decisions",
        "shortTitle": "Design the next decision",
        "title": "8. Optimize what the next observation can teach",
        "status": "Outlook · June 2026 Perspective submission; proposed framework",
        "hook": "The most certain classification may not be the most valuable next observation. An uncertain, fast-fading source could teach us more.",
        "input": "Evolving measurements, uncertainties and a finite observing budget are the inputs envisioned by Bom and colleagues.",
        "mechanism": "Their decision-aware framework proposes maintaining a representation of the source state, then selecting follow-up by expected scientific value under resource constraints. Human supervision and auditable choices are part of the design.",
        "evidence": "The June 2026 manuscript is a submitted Perspective: it develops an agenda, not a measured deployment of an agent operating Rubin.",
        "limit": "Better classification accuracy does not by itself prove better use of telescope time. A policy needs an explicit scientific objective and evaluation of missed opportunities, costs and uncertainty.",
        "connection": "A possible project experiment is to freeze a candidate queue and compare review policies at the same human-review budget. Define the endpoint and held-out population before testing. This is proposed work; the watcher and model deployment remain unchanged.",
        "sources": [
          "decision-ai"
        ],
        "lessons": [
          "capstone",
          "uncertainty"
        ],
        "related": [
          {
            "title": "Wider astronomy: cosmology also depends on calibrated errors",
            "text": "The DESC January 2026 white paper discusses photometric redshifts (distance clues from broad-band colors), weak-lensing inference, transient classification and simulations. It is a collaboration research agenda, not one new cosmological measurement. Domain shift and model misspecification matter because errors can propagate into the final scientific inference.",
            "sources": [
              "desc-ai"
            ]
          }
        ],
        "reflection": {
          "question": "Carry one idea back to the capstone",
          "answer": "Choose one input or decision to change. State the failure it addresses, the independent evaluation population, the fixed control or review budget, and the observation that would make you reject the idea. A useful negative result still narrows the next experiment."
        }
      }
    ]
  },
  "units": [
    {
      "id": "sky",
      "title": "Read the sky",
      "subtitle": "From photons to a believable dip",
      "outcome": "Interpret a light curve, estimate a planet radius and distinguish observing limits from astrophysics.",
      "exam": [
        {
          "type": "single",
          "prompt": "Case: a 900 ppm undiluted transit crosses a uniform Sun-sized star. Which radius estimate follows?",
          "options": [
            "3.27 Earth radii",
            "0.0981 Earth radii, using depth directly as a radius ratio",
            "32.7 Earth radii, after interpreting 900 ppm as 9%",
            "An absolute radius cannot be estimated even with the stated stellar radius"
          ],
          "answer": 0,
          "explanation": "√0.0009 × 109 = 3.27 Earth radii; depth does not give mass.",
          "id": "sky-exam1",
          "lesson": "light"
        },
        {
          "type": "single",
          "prompt": "Dips at days 4 and 24, with a gap at day 14: which conclusion is defensible?",
          "options": [
            "Both 10- and 20-day solutions deserve testing.",
            "20 days is unique because only two dips were detected.",
            "10 days is ruled out because no intermediate event was measured.",
            "The shorter period must be preferred because it predicts more cycles."
          ],
          "answer": 0,
          "explanation": "The intermediate event of a 10-day orbit was not observed because that interval lacks data.",
          "id": "sky-exam2",
          "lesson": "orbits"
        },
        {
          "type": "multi",
          "prompt": "You receive a new TESS file. What should you inspect before reusing Kepler preprocessing?",
          "options": [
            "Time units and zero point",
            "Cadence, quality flags and flux columns",
            "Crowding and target metadata",
            "Whether its filename sounds planetary"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The measurement contract and observing context determine valid transformations.",
          "id": "sky-exam3",
          "lesson": "missions"
        },
        {
          "type": "single",
          "prompt": "A target-shaped dip localizes on a faint neighbor. What takes priority?",
          "options": [
            "Re-evaluate the host and background-eclipse scenario.",
            "Retain the target-host interpretation because the folded transit is symmetric.",
            "Treat localization as irrelevant once the depth implies a planetary radius.",
            "Average the neighboring and target stellar radii for a final radius estimate."
          ],
          "answer": 0,
          "explanation": "Spatial evidence changes the hypothesis even when the aperture light curve looks convincing.",
          "id": "sky-exam4",
          "lesson": "impostors"
        }
      ]
    },
    {
      "id": "search",
      "title": "Turn data into detections",
      "subtitle": "Python, preprocessing and period searches",
      "outcome": "Follow the full path from time-stamped measurements to a reproducible candidate proposal.",
      "exam": [
        {
          "type": "single",
          "prompt": "time=[1,2,3], flux=[1,NaN,0.98]. After removing the NaN row, which pair is correct?",
          "options": [
            "time=[1,3], flux=[1,0.98]",
            "time=[1,2], flux=[1,0.98]",
            "time=[1,2,3], flux=[1,0.98]",
            "time=[3,1], flux=[1,0.98]"
          ],
          "answer": 0,
          "explanation": "The same row mask preserves alignment.",
          "id": "search-exam1",
          "lesson": "arrays"
        },
        {
          "type": "single",
          "prompt": "A detrending change improves smoothness but halves injected transit depths. Adopt it?",
          "options": [
            "No; quantify the lost signal and compare end-to-end recovery first.",
            "Yes; the reduced scatter guarantees higher sensitivity after normalizing depth.",
            "Yes; training a larger classifier guarantees recovery of the removed morphology.",
            "Choose the setting that gives the highest known-planet score on the final audit."
          ],
          "answer": 0,
          "explanation": "An attractive residual plot does not compensate for measured signal suppression.",
          "id": "search-exam2",
          "lesson": "clean"
        },
        {
          "type": "number",
          "prompt": "For t=18, t₀=3 and P=6 days, what is phase in [0,1)?",
          "answer": 0.5,
          "tolerance": 0.0001,
          "unit": "phase",
          "explanation": "(18 − 3)/6 = 2.5; fractional part = 0.5.",
          "id": "search-exam3",
          "lesson": "fold"
        },
        {
          "type": "single",
          "prompt": "A new TLS search reports more candidates than BLS. What additional comparison is essential?",
          "options": [
            "Recovery and false alerts on the same locked evaluation sample",
            "The two methods’ maximum search statistics, even if differently normalized",
            "The total alerts alone, because more alerts imply better completeness",
            "Only the model confidence of each method’s highest-ranked candidate"
          ],
          "answer": 0,
          "explanation": "More alerts may reflect higher completeness, more false alarms or both.",
          "id": "search-exam4",
          "lesson": "aliases"
        }
      ]
    },
    {
      "id": "statistics",
      "title": "Learn to trust a result",
      "subtitle": "Noise, metrics, leakage and probability",
      "outcome": "Explain what a score means and design an evaluation that survives scrutiny.",
      "exam": [
        {
          "type": "number",
          "prompt": "A white-noise calculation has δ=100 ppm, σ=500 ppm and n=100. Calculate SNR.",
          "answer": 2,
          "tolerance": 0.001,
          "unit": "SNR",
          "explanation": "100 × √100 / 500 = 2, under the stated independence assumption.",
          "id": "statistics-exam1",
          "lesson": "noise"
        },
        {
          "type": "number",
          "prompt": "Among 50 alerts, 10 are real positives. What is precision in percent?",
          "answer": 20,
          "tolerance": 0.01,
          "unit": "%",
          "explanation": "10/50 = 20%; alert count alone says nothing about purity.",
          "id": "statistics-exam2",
          "lesson": "metrics"
        },
        {
          "type": "single",
          "prompt": "An augmented light curve derived from a training star appears in the audit. What is the key problem?",
          "options": [
            "Dependence crosses the split boundary.",
            "Only exact byte-identical copies cause leakage, so augmentation is safe.",
            "The audit is independent as long as its row identifiers are new.",
            "A different random seed makes the derived light curve an independent star."
          ],
          "answer": 0,
          "explanation": "Derived examples must remain with the original source group.",
          "id": "statistics-exam3",
          "lesson": "splits"
        },
        {
          "type": "single",
          "prompt": "A catalog-trained calibrator assigns 0.9 to an unmatched blind signal. What must be checked before calling it 90% planet probability?",
          "options": [
            "Whether calibration, labels and alternatives apply to this selected blind-search population",
            "Only whether the calibration curve looked good on the training cohort",
            "Whether the three model seeds agree within one percentage point",
            "Whether the classifier’s overall audit AP exceeds 0.9"
          ],
          "answer": 0,
          "explanation": "Calibration validity is conditional on population and task; astrophysical validation requires additional modeling.",
          "id": "statistics-exam4",
          "lesson": "probability"
        }
      ]
    },
    {
      "id": "learning",
      "title": "How a model learns",
      "subtitle": "Weights → prediction → loss → gradients → updates",
      "outcome": "Calculate a training step and explain initialization, randomness, regularization and learning curves.",
      "exam": [
        {
          "type": "number",
          "prompt": "For x=[1,2], w=[3,−1], b=0.5, calculate the pre-activation z.",
          "answer": 1.5,
          "tolerance": 0.0001,
          "unit": "logit",
          "explanation": "3×1 − 1×2 + 0.5 = 1.5.",
          "id": "learning-exam1",
          "lesson": "neurons"
        },
        {
          "type": "number",
          "prompt": "For x=1, y=3, w=1, squared loss ½(wx−y)² and learning rate 0.2, calculate the updated weight.",
          "answer": 1.4,
          "tolerance": 0.0001,
          "unit": "weight",
          "explanation": "Gradient=(1−3)×1=−2; update=1−0.2×(−2)=1.4.",
          "id": "learning-exam2",
          "lesson": "gradients"
        },
        {
          "type": "single",
          "prompt": "Model A uses ten times as many optimizer updates as B and wins. What remains unclear?",
          "options": [
            "Whether architecture or extra training exposure caused the gain",
            "Whether the larger number of updates automatically makes the audit independent",
            "Whether a higher score makes initialization variability irrelevant",
            "Whether equal batch size alone makes total compute exposure equal"
          ],
          "answer": 0,
          "explanation": "Compute and tuning are confounders unless controlled or explicitly accounted for.",
          "id": "learning-exam3",
          "lesson": "training"
        },
        {
          "type": "multi",
          "prompt": "A reproducibility record should retain which items?",
          "options": [
            "Training and data-split seeds",
            "Code, dependency and input versions",
            "Checkpoint and preprocessing hashes",
            "Only the best final score"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Reproduction requires the full computational state and provenance, not a single metric.",
          "id": "learning-exam4",
          "lesson": "seeds"
        }
      ]
    },
    {
      "id": "architectures",
      "title": "Choose a model with a reason",
      "subtitle": "CNNs, trees, recurrent models and attention",
      "outcome": "Explain what each architecture can see, what it assumes and what a fair comparison requires.",
      "exam": [
        {
          "type": "number",
          "prompt": "A 1D input has 100 bins, kernel width 5, stride 1 and no padding. What is the output length?",
          "answer": 96,
          "tolerance": 0,
          "unit": "bins",
          "explanation": "100 − 5 + 1 = 96.",
          "id": "architectures-exam1",
          "lesson": "cnn"
        },
        {
          "type": "single",
          "prompt": "Trees with extra centroid features beat a flux-only CNN. Which next ablation isolates information gain?",
          "options": [
            "Give both methods matched diagnostics and compare with and without centroids.",
            "Let only the CNN train longer until its score matches the tree.",
            "Compare the best seed from each method on separate audit cohorts.",
            "Remove centroid features only from the model that originally lost."
          ],
          "answer": 0,
          "explanation": "Matched inputs and controlled feature removal help separate architecture from evidence.",
          "id": "architectures-exam2",
          "lesson": "alternatives"
        },
        {
          "type": "number",
          "prompt": "Attention weights 0.2, 0.3 and 0.5 combine values 1, 2 and 4. What is the scalar output?",
          "answer": 2.8,
          "tolerance": 0.0001,
          "unit": "output",
          "explanation": "0.2×1 + 0.3×2 + 0.5×4 = 2.8.",
          "id": "architectures-exam3",
          "lesson": "attention"
        },
        {
          "type": "single",
          "prompt": "Masked-pretraining loss improves, but shallow-transit recovery worsens. What is the scientific conclusion?",
          "options": [
            "The pretraining objective improved while the target task deteriorated.",
            "Lower reconstruction loss proves the representation is better for every task.",
            "The detector improved because rare events should be reconstructed as normal variability.",
            "The shallow-event metric should be replaced with the favorable pretraining metric."
          ],
          "answer": 0,
          "explanation": "A surrogate objective must be validated against the actual scientific endpoint.",
          "id": "architectures-exam4",
          "lesson": "representation"
        }
      ]
    },
    {
      "id": "transfer",
      "title": "Transfer, uncertainty and the research frontier",
      "subtitle": "From Kepler to TESS, with evidence",
      "outcome": "Explain DANN’s actual gradient game and compare it with fine-tuning, pooling and recent approaches.",
      "exam": [
        {
          "type": "single",
          "prompt": "A pooled model loses to TESS-only on the same audit. Which conclusion is supported?",
          "options": [
            "Pooling did not help under this evaluated setup.",
            "Source-domain information is fundamentally unusable for every TESS application.",
            "A more complex domain adversary must therefore improve the same audit.",
            "The target-only model must have leaked because it used fewer total labels."
          ],
          "answer": 0,
          "explanation": "The result is conditional on data, budget, optimization and evaluation; investigate causes without overgeneralizing.",
          "id": "transfer-exam1",
          "lesson": "transfer"
        },
        {
          "type": "number",
          "prompt": "For task gradient 1, domain gradient 4 and λ=0.5, calculate the extractor gradient.",
          "answer": -1,
          "tolerance": 0.0001,
          "unit": "gradient",
          "explanation": "1 − 0.5×4 = −1. The adversarial contribution can reverse the combined direction.",
          "id": "transfer-exam2",
          "lesson": "dann"
        },
        {
          "type": "single",
          "prompt": "An OOD gate lowers error among accepted cases while rejecting half the archive. What must be reported?",
          "options": [
            "Both the error reduction and 50% coverage with review implications",
            "Only accepted-case error, because deferred cases are outside the deployed system",
            "Only the number rejected, because accepted predictions are automatically reliable",
            "The accepted-case error as the error rate of the entire original archive"
          ],
          "answer": 0,
          "explanation": "Selective performance without coverage hides the operational cost.",
          "id": "transfer-exam3",
          "lesson": "uncertainty"
        },
        {
          "type": "single",
          "prompt": "A 2026 paper reports strong selected-control recovery. What is a useful next validation?",
          "options": [
            "A locked blind evaluation with realistic negatives and documented selection",
            "A larger known-positive sample with no non-planet controls, reported as purity",
            "Averaging the published recovery percentage with our CNN scores",
            "Choosing another threshold on the same controls until every one is recovered"
          ],
          "answer": 0,
          "explanation": "Blind false alarms and selection determine whether control recovery generalizes.",
          "id": "transfer-exam4",
          "lesson": "frontier"
        }
      ]
    },
    {
      "id": "vetting",
      "title": "Become a careful vetter",
      "subtitle": "From an unmatched row to a defensible dossier",
      "outcome": "Choose the next observation or diagnostic and distinguish candidate registration from validation.",
      "exam": [
        {
          "type": "single",
          "prompt": "The current feature odd_even compares alternating phase bins. Can it stand in for an event-by-event binary test?",
          "options": [
            "No; the two statistics measure different things.",
            "Yes, because both use an alternating even/odd assignment.",
            "Yes, after rescaling the phase-bin statistic to lie between zero and one.",
            "Only when the folded bins outnumber the individual transit events."
          ],
          "answer": 0,
          "explanation": "Feature names can be misleading; inspect their implemented definition.",
          "id": "vetting-exam1",
          "lesson": "vetter"
        },
        {
          "type": "single",
          "prompt": "Difference images favor a neighboring source. What must be revisited?",
          "options": [
            "Host identity, contamination and inferred physical parameters",
            "Only the final classification threshold, keeping the target radius fixed",
            "Only the time binning, because pixels cannot change the host interpretation",
            "The model seed, because a spatial offset is a source of training randomness"
          ],
          "answer": 0,
          "explanation": "Spatial evidence changes which physical system the event belongs to.",
          "id": "vetting-exam2",
          "lesson": "pixels"
        },
        {
          "type": "multi",
          "prompt": "Which claims need more than a catalog non-match?",
          "options": [
            "A new planet discovery",
            "An astrophysical false-positive probability",
            "A confirmed planet interpretation",
            "A statement that this checker found no match"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Only the last claim is directly supported by the checker outcome.",
          "id": "vetting-exam3",
          "lesson": "validation"
        },
        {
          "type": "single",
          "prompt": "Which action best addresses the 23 September unmatched case evidence?",
          "options": [
            "Resolve event/alias and source-localization evidence.",
            "Promote it because the DANN mean exceeds the reference score.",
            "Calibrate the current score using its ranking among the 44 retained controls.",
            "Assume consecutive observed dips define a unique orbit despite missing coverage."
          ],
          "answer": 0,
          "explanation": "Timing and host uncertainties are the current scientific bottlenecks.",
          "id": "vetting-exam4",
          "lesson": "case"
        }
      ]
    },
    {
      "id": "project",
      "title": "Understand this repository",
      "subtitle": "Read the implementation and the completed results",
      "outcome": "Trace the model inputs, distinguish experiments and operate the website without confusing live data with backups.",
      "exam": [
        {
          "type": "single",
          "prompt": "A checkpoint loads but duration changed from hours to days. What happened?",
          "options": [
            "The semantic input contract changed despite compatible shapes.",
            "The frozen normalizer necessarily corrects any unit conversion by itself.",
            "The classifier is unaffected because duration and period are correlated.",
            "The representation is still equivalent as long as the values remain finite."
          ],
          "answer": 0,
          "explanation": "The network’s learned relationship to that scalar depends on the training unit convention.",
          "id": "project-exam1",
          "lesson": "contract"
        },
        {
          "type": "single",
          "prompt": "DANN is stable across seeds but worse in mean AP than pooling. What is a correct description?",
          "options": [
            "Consistent training outcomes did not produce a demonstrated performance gain.",
            "Low seed spread means the DANN mean is the most accurate candidate probability.",
            "Stable optimization proves the larger AP of pooling is just random noise.",
            "Seed agreement is enough to promote DANN despite the task metric."
          ],
          "answer": 0,
          "explanation": "Stability, ranking quality and calibration are separate properties.",
          "id": "project-exam2",
          "lesson": "results"
        },
        {
          "type": "single",
          "prompt": "The remote Research server responds but the laptop browser cannot connect after forwarding stopped. What should be restored?",
          "options": [
            "The correct local-to-remote port forward",
            "All model weights",
            "The planet catalog labels",
            "A new training seed"
          ],
          "answer": 0,
          "explanation": "The service and the route used to reach it are separate.",
          "id": "project-exam3",
          "lesson": "operations"
        },
        {
          "type": "single",
          "prompt": "New review notes were added after the last backup. What protects them remotely?",
          "options": [
            "A new verified snapshot including the changed database and references, then the chosen remote backup step",
            "Refreshing the tab",
            "Pushing an unrelated README edit",
            "Reusing an archive created before the notes existed"
          ],
          "answer": 0,
          "explanation": "Old snapshots cannot contain future changes.",
          "id": "project-exam4",
          "lesson": "reproduce"
        }
      ]
    },
    {
      "id": "research",
      "title": "Develop and test a research idea",
      "subtitle": "Turn a limitation into a controlled experiment",
      "outcome": "Design a falsifiable study, evaluate discovery completeness and defend a bounded contribution.",
      "exam": [
        {
          "type": "single",
          "prompt": "A method recovers many deep injections but misses shallow ones. Which report is most informative?",
          "options": [
            "Recovery as a function of signal depth and other relevant conditions",
            "One overall recovery number without the injection distribution",
            "Recovery only above the depth where every method succeeds",
            "The largest model output among the recovered injections"
          ],
          "answer": 0,
          "explanation": "A selection function reveals where detection succeeds and fails.",
          "id": "research-exam1",
          "lesson": "injections"
        },
        {
          "type": "single",
          "prompt": "You add a new input, larger model and longer training simultaneously and win. What remains unresolved?",
          "options": [
            "Which change caused the gain",
            "Whether a positive total gain removes the need for baseline matching",
            "Whether all three changes are each individually beneficial",
            "Whether an ablation can be replaced by testing only the best seed"
          ],
          "answer": 0,
          "explanation": "Controlled ablations are needed to isolate contributions.",
          "id": "research-exam2",
          "lesson": "ablation"
        },
        {
          "type": "single",
          "prompt": "A close paper already uses the proposed architecture. What is a constructive next step?",
          "options": [
            "Identify whether a distinct, evidence-backed task or evaluation gap remains.",
            "Claim novelty because the architecture has a different name in our code.",
            "Treat use on one more known control star as proof of general superiority.",
            "Avoid comparing against the close paper because it weakens the claim."
          ],
          "answer": 0,
          "explanation": "A contribution can be about a different justified question, but must acknowledge prior methods.",
          "id": "research-exam3",
          "lesson": "papers"
        },
        {
          "type": "single",
          "prompt": "The prespecified study finds no meaningful benefit. What should be retained?",
          "options": [
            "The full results, limitations and what the hypothesis test rules out",
            "Only the secondary metric that improved after the primary endpoint failed",
            "Only the seed most consistent with the original hypothesis",
            "Only successful runs, leaving failures out of the reported compute budget"
          ],
          "answer": 0,
          "explanation": "Complete evidence supports reproducibility and better future decisions.",
          "id": "research-exam4",
          "lesson": "capstone"
        }
      ]
    }
  ],
  "modules": [
    {
      "id": "light",
      "unit": "sky",
      "order": 1,
      "title": "What does a light curve actually measure?",
      "hook": "A star becomes 0.04% fainter. Start with what the telescope measured before deciding what caused it.",
      "minutes": 35,
      "objectives": [
        "Read relative flux and ppm.",
        "Calculate a radius ratio from transit depth.",
        "Explain why a dip alone does not identify a planet."
      ],
      "sections": [
        {
          "title": "Begin with the measurement",
          "paragraphs": [
            "Imagine taking a brightness measurement of the same star every few minutes. Put the times in one column and the brightness values in another: you have a light curve. Each measurement also has an uncertainty, and a quality flag may tell you that the instrument had a problem. To compare measurements, we often divide brightness by its usual value outside a dip. This gives relative flux. A value of 1 is the baseline; 0.999 means the star appears 0.1% fainter. So the plot shows how much light arrived, not a picture of the planet itself.",
            "A part per million (ppm) is 0.000001 of the baseline. Multiply fractional depth by 1,000,000 to express it in ppm. Keep flux, fractional depth and percent distinct: a depth of 0.01 is 1%, not 0.01%."
          ]
        },
        {
          "title": "The first physical model",
          "paragraphs": [
            "For a small opaque planet fully crossing a uniformly bright stellar disk, depth δ ≈ (Rp/R★)². The symbol δ is the fraction of starlight blocked; Rp and R★ must have the same units. Rearranging gives Rp/R★ ≈ √δ. The square arises because the blocked area depends on radius squared.",
            "To obtain a physical planet radius, multiply by the stellar radius. An uncertain host radius therefore makes the planet radius uncertain even if the depth is precisely measured. A Sun-sized star is approximately 109 Earth radii for our teaching calculations."
          ]
        },
        {
          "title": "Where this approximation stops",
          "paragraphs": [
            "Real stars are darker toward their edge: limb darkening changes the transit profile. A grazing transit may never place the entire planet disk in front of the star. Light from another star dilutes the dip. These effects require a physical transit model and information about the host. A stellar eclipse or an instrumental event can also lower the measured flux. Depth is a geometric clue, not a diagnosis."
          ]
        }
      ],
      "example": {
        "title": "A 400 ppm dip around a Sun-sized star",
        "steps": [
          "Convert: δ = 400 / 1,000,000 = 0.0004.",
          "Take the square root: Rp/R★ = 0.02.",
          "Scale: Rp ≈ 0.02 × 109 = 2.18 Earth radii."
        ],
        "answer": "The simplified estimate is 2.18 Earth radii, conditional on the assumed host and an undiluted transit."
      },
      "project": "The watcher stores proposed dips. Its CNN score is a separate learned ranking; it does not replace the depth calculation or establish which star dimmed.",
      "sources": [
        "tess",
        "crowd"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "Relative flux falls from 1 to 0.9995. What is the depth in ppm?",
          "answer": 500,
          "tolerance": 0.1,
          "unit": "ppm",
          "explanation": "(1 − 0.9995) × 1,000,000 = 500 ppm.",
          "id": "light-q1",
          "lesson": "light"
        },
        {
          "type": "number",
          "prompt": "Under the uniform-disk approximation, a 1% depth gives what Rp/R★?",
          "answer": 0.1,
          "tolerance": 0.0001,
          "unit": "radius ratio",
          "explanation": "1% = 0.01 and √0.01 = 0.1. Taking the depth itself would confuse area with radius.",
          "id": "light-q2",
          "lesson": "light"
        },
        {
          "type": "single",
          "prompt": "The same fractional transit depth occurs around stars of radius 1 and 2 solar radii. Which inferred planet is larger?",
          "options": [
            "The planet around the larger star is twice as large.",
            "Both planets have the same physical radius.",
            "The planet around the larger star is four times larger.",
            "Depth cannot constrain even a radius ratio."
          ],
          "answer": 0,
          "explanation": "The depth fixes Rp/R★ under the approximation, so doubling R★ doubles Rp.",
          "id": "light-q3",
          "lesson": "light"
        },
        {
          "type": "multi",
          "prompt": "Which information is needed to turn an observed dip into a trustworthy physical radius estimate? Select all that apply.",
          "options": [
            "Stellar radius",
            "Contamination and host identity",
            "An assumption or fit for transit geometry",
            "A high CNN score alone"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Radius, dilution and geometry affect the inference. A ranking score cannot supply them.",
          "id": "light-q4",
          "lesson": "light"
        },
        {
          "type": "single",
          "prompt": "Why does the depth scale with radius squared?",
          "options": [
            "It measures blocked area relative to stellar area.",
            "Orbital period is squared.",
            "The detector squares photon counts.",
            "Every transit contains two events."
          ],
          "answer": 0,
          "explanation": "For circular disks area is πr²; the π factors cancel in the area ratio.",
          "id": "light-q5",
          "lesson": "light"
        },
        {
          "type": "single",
          "prompt": "A clean dip has been found. What claim is justified immediately?",
          "options": [
            "A dimming event needs investigation.",
            "A planet has been confirmed.",
            "Its mass is known.",
            "It is absent from every catalog."
          ],
          "answer": 0,
          "explanation": "Detecting a brightness decrease is earlier in the evidence chain than determining its cause.",
          "id": "light-q6",
          "lesson": "light"
        }
      ],
      "lab": "transit",
      "code": null,
      "takeaway": "Depth is the fraction of the combined light that disappears. Under the simple undiluted, uniform-disk model, take its square root to estimate the planet-to-star radius ratio.",
      "pitfall": "Convert percent or ppm to a fraction before taking the square root. A 1% dip means δ = 0.01, not δ = 1.",
      "prerequisite": null
    },
    {
      "id": "orbits",
      "unit": "sky",
      "order": 2,
      "title": "Geometry, periods and the observing window",
      "hook": "Two identical planets can produce very different light curves because their paths and observing windows differ.",
      "minutes": 35,
      "objectives": [
        "Distinguish period, epoch and duration.",
        "Use simple orbital scalings.",
        "Explain why missing data is not a missing transit."
      ],
      "sections": [
        {
          "title": "Three coordinates for a repeated event",
          "paragraphs": [
            "To describe a repeating dip, you need three different pieces of information. The period P tells you how long you wait between cycles. The epoch t₀ marks one reference mid-transit time. The duration T tells you how long a single transit lasts. Once you know P and t₀, predict later event centers with tₙ = t₀ + nP: start at the reference event and add n whole periods. The reference event has n = 0. Keep the time system and units attached to these numbers; hours, days and different time zero points are not interchangeable."
          ]
        },
        {
          "title": "The orbit sets the scale",
          "paragraphs": [
            "For a planet much less massive than its star, Kepler’s third law is P² ∝ a³/M★, where a is orbital size and M★ is stellar mass. Around a Sun-like star, P in years and a in astronomical units give approximately P² = a³. Thus a planet at 4 AU has a period near 8 years. This relation constrains an orbit; it does not measure planet mass from transit depth.",
            "Only suitably aligned orbits transit. For a circular orbit the geometric transit probability is approximately (R★ + Rp)/a. A longer orbit is usually less likely to transit and gives fewer events during a fixed observing baseline."
          ]
        },
        {
          "title": "Read duration with geometry in mind",
          "paragraphs": [
            "The impact parameter describes how far the path passes from the stellar center in units of stellar radius. Larger impact parameters usually shorten the chord across the star. A central circular transit has roughly T ≈ (P/π)(R★/a) when R★/a is small and the planet is small. Eccentricity, stellar density and impact parameter can trade off.",
            "A telescope’s observing window contains gaps. A predicted event inside a gap is untested, not disproved. Inspect the original timestamps before rejecting a period or treating two separated events as consecutive cycles."
          ]
        }
      ],
      "example": {
        "title": "Count the unseen possibilities",
        "steps": [
          "Dips are observed at days 2 and 22; there is no data from days 9–15.",
          "P = 20 days connects consecutive events.",
          "P = 10 days predicts an intermediate transit on day 12, inside the gap."
        ],
        "answer": "Both periods remain possible from these event times; more coverage or other evidence is needed."
      },
      "project": "The 25.3244-day unmatched signal has an unresolved cycle/alias question. Some predicted intermediate events fall outside usable coverage; the displayed period is not a secure orbital solution.",
      "sources": [
        "tess"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "With t₀ = 3 days and P = 5 days, what is t₃?",
          "answer": 18,
          "tolerance": 0.001,
          "unit": "days",
          "explanation": "t₃ = 3 + 3 × 5 = 18 days. The reference event has n = 0.",
          "id": "orbits-q1",
          "lesson": "orbits"
        },
        {
          "type": "number",
          "prompt": "A Sun-like star has a planet at 4 AU. Using P² = a³, calculate P in years.",
          "answer": 8,
          "tolerance": 0.001,
          "unit": "years",
          "explanation": "P = √(4³) = √64 = 8 years.",
          "id": "orbits-q2",
          "lesson": "orbits"
        },
        {
          "type": "single",
          "prompt": "What does transit duration describe?",
          "options": [
            "The interval occupied by a transit event.",
            "The time between orbital cycles.",
            "The age of the planet.",
            "The observing campaign length."
          ],
          "answer": 0,
          "explanation": "Period, duration and observing baseline are different quantities.",
          "id": "orbits-q3",
          "lesson": "orbits"
        },
        {
          "type": "single",
          "prompt": "A period predicts an extra transit during a data gap. What follows?",
          "options": [
            "That prediction cannot be tested in the gap.",
            "The period is disproved.",
            "The transit must have occurred.",
            "The object has a changing radius."
          ],
          "answer": 0,
          "explanation": "Absence of measurements supplies no event-depth constraint.",
          "id": "orbits-q4",
          "lesson": "orbits"
        },
        {
          "type": "multi",
          "prompt": "Which can affect measured transit duration?",
          "options": [
            "Orbital speed",
            "Impact parameter",
            "Stellar radius",
            "The arbitrary catalog identifier"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The transit chord and crossing speed determine duration; an identifier does not.",
          "id": "orbits-q5",
          "lesson": "orbits"
        },
        {
          "type": "single",
          "prompt": "Why are many real planets absent from a transit survey?",
          "options": [
            "Their orbits do not cross the star from our viewpoint.",
            "Every planet dims its star once per day.",
            "Only planets with atmospheres transit.",
            "Non-transiting planets have zero mass."
          ],
          "answer": 0,
          "explanation": "Transit detection requires a viewing geometry that causes an eclipse.",
          "id": "orbits-q6",
          "lesson": "orbits"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Period spaces the events; epoch anchors one event; duration describes the width of each event. Use all three together with the actual observation times.",
      "pitfall": "An event predicted inside a data gap has not been checked. Do not reject a period just because no measurement exists there.",
      "prerequisite": "light"
    },
    {
      "id": "missions",
      "unit": "sky",
      "order": 3,
      "title": "Kepler and TESS: two different experiments",
      "hook": "The same planet is easier to recognize in one survey than another. Learn what changes before moving a model.",
      "minutes": 35,
      "objectives": [
        "Read cadence and baseline from data products.",
        "Distinguish pixels, light curves and catalog labels.",
        "Predict practical sources of mission shift."
      ],
      "sections": [
        {
          "title": "Cadence and baseline answer different questions",
          "paragraphs": [
            "Suppose you want to see the shape of a dip and also find out whether it repeats. These need different kinds of coverage. Cadence is the spacing between samples: shorter spacing gives you more points across one transit. Exposure time tells you how much of the changing signal each measurement averages together. Baseline is the total time span covered: a longer baseline can reveal more orbital cycles. Gaps still matter. A file with many rows can have poor coverage of the moments you actually need, so inspect the timestamps rather than inferring coverage from row count alone.",
            "Kepler’s original mission repeatedly observed a field over years. TESS observes sectors typically lasting about 27 days, with some stars seen in many sectors. Cadence and data products vary over TESS mission phases. Read the actual file header instead of applying one cadence to all TESS data."
          ]
        },
        {
          "title": "Know what each product contains",
          "paragraphs": [
            "A full-frame image records a wide detector view. A target pixel file contains a time series of pixels around a selected target. A light-curve file contains extracted flux and auxiliary columns. SPOC and QLP are processing pipelines with different product paths and selection effects. A TIC or KIC is an identifier for a cataloged target, not a planet label.",
            "A TCE is a threshold-crossing event: a search-generated signal for evaluation. A TOI is a TESS Object of Interest. Catalog dispositions describe the current assessment and can change. Unlabeled means unknown, not negative."
          ]
        },
        {
          "title": "Why transferring a classifier is a scientific experiment",
          "paragraphs": [
            "Mission changes affect sampling, pixel scale, crowding, noise, observing baseline and label selection. A model can learn shortcuts from these differences. More Kepler training examples do not automatically make a TESS detector better. Control the input transformation, group related stars correctly and evaluate on the population that will receive the model. Mission adaptation begins with measurement and labeling differences, not with choosing a fashionable network."
          ]
        },
        {
          "title": "Availability defines the population",
          "paragraphs": [
            "The fresh classifier study registered 295 candidate hosts before inference, but 281 had no public native 120-second SPOC product. All 14 available products passed the unchanged preparation. This is an archive-availability restriction, not a claim that cleaning destroyed 281 usable light curves. A result on these available hosts may not transfer to other cadences, pipelines or fainter targets."
          ]
        }
      ],
      "example": {
        "title": "A 20-day orbit in a 27-day sector",
        "steps": [
          "A sector covers about 1.35 orbital cycles.",
          "Depending on phase and gaps, it may contain one or two transits.",
          "Combining additional sectors can test repeatability, but gaps still create aliases."
        ],
        "answer": "A short sector does not provide the same period evidence as several continuous years."
      },
      "project": "The 28 September snapshot has 18 selected archival targets, a six-hour configured poll and at most two products per cycle. The two fixed controls belong to the 23 September setup. Neither is archive-wide coverage. Kepler supplies archival training examples; this is why a TESS-facing project contains a Kepler-trained reference model.",
      "sources": [
        "tess",
        "lightkurve"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "Ignoring gaps, how many 2-minute samples fit in a 2-hour transit?",
          "answer": 60,
          "tolerance": 0,
          "unit": "samples",
          "explanation": "2 hours = 120 minutes; 120 / 2 = 60 samples.",
          "id": "missions-q1",
          "lesson": "missions"
        },
        {
          "type": "single",
          "prompt": "Which quantity most directly increases the number of orbital cycles observed?",
          "options": [
            "Longer usable time baseline",
            "A larger catalog identifier",
            "More decimal places in flux",
            "A different plot color"
          ],
          "answer": 0,
          "explanation": "Longer coverage can capture more events; faster cadence mainly resolves each event.",
          "id": "missions-q2",
          "lesson": "missions"
        },
        {
          "type": "multi",
          "prompt": "Which are plausible Kepler-to-TESS domain shifts?",
          "options": [
            "Crowding",
            "Cadence and integration time",
            "Noise and target selection",
            "The mathematical definition of a square root"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Mission properties and sample selection change; mathematical operations do not.",
          "id": "missions-q3",
          "lesson": "missions"
        },
        {
          "type": "single",
          "prompt": "What is a TCE?",
          "options": [
            "A search signal that crossed a detection threshold",
            "A confirmed planet",
            "A stellar mass measurement",
            "A specific neural network architecture"
          ],
          "answer": 0,
          "explanation": "A TCE needs classification and vetting after detection.",
          "id": "missions-q4",
          "lesson": "missions"
        },
        {
          "type": "single",
          "prompt": "What label should an uninvestigated signal receive during supervised evaluation?",
          "options": [
            "Unknown or excluded under a stated policy",
            "Definitely a false positive",
            "Definitely a planet",
            "Whichever label balances the dataset"
          ],
          "answer": 0,
          "explanation": "Unlabeled examples must not silently become negative truth labels.",
          "id": "missions-q5",
          "lesson": "missions"
        },
        {
          "type": "single",
          "prompt": "In the 23 September 2026 known-object-control snapshot, what was the watcher's sky coverage?",
          "options": [
            "New products for two configured control targets",
            "Every TESS star and every Kepler star",
            "Only newly confirmed planets",
            "A guaranteed full-sky discovery survey"
          ],
          "answer": 0,
          "explanation": "That dated setup checked two configured controls. By 28 September a bounded archival-discovery pilot had 18 selected targets; neither snapshot represents the whole archive.",
          "id": "missions-q6",
          "lesson": "missions"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Cadence helps resolve a transit; baseline helps establish repetition. Mission differences also change the inputs and labels a model learns from.",
      "pitfall": "A file name or mission name is not enough to determine cadence or time units. Read the product metadata.",
      "prerequisite": "orbits"
    },
    {
      "id": "impostors",
      "unit": "sky",
      "order": 4,
      "title": "The impostor line-up",
      "hook": "A plausible U-shaped dip can still come from a neighboring eclipsing binary. Build a differential diagnosis.",
      "minutes": 35,
      "objectives": [
        "Recognize astrophysical and instrumental alternatives.",
        "Use dilution arithmetic.",
        "Choose evidence that distinguishes hypotheses."
      ],
      "sections": [
        {
          "title": "Start with competing causes",
          "paragraphs": [
            "When you see a dip, keep several possible explanations open. A planet can block starlight, but so can another star in an eclipsing binary. If that binary shares an aperture with a brighter star, their combined light can make a deep stellar eclipse look shallow. A grazing eclipse, stellar variability, scattered light or a spacecraft event can also trigger the search. Vetting means collecting evidence that helps you choose between these explanations. Calling this signal a false positive means that a non-planet explanation accounts for it; it does not mean the star cannot host any planets.",
            "A V shape, strong secondary eclipse or unequal alternating event depths can increase concern about a stellar binary. These are diagnostic clues with exceptions. Grazing planets can be V-shaped; some real planets have measurable secondary eclipses. Combine evidence rather than declaring one morphology decisive."
          ]
        },
        {
          "title": "Dilution changes what the eye sees",
          "paragraphs": [
            "Let c be the fraction of total out-of-eclipse light contributed by unrelated constant sources. If the target is actually eclipsed, observed depth δobs = (1 − c)δtrue. Solving for the true depth requires the correct host and contamination fraction. If a faint neighbor is the eclipsing object instead, use that neighbor’s share of the total light. A 50% stellar eclipse on a source contributing 1% of total light appears as a 0.5% dip."
          ]
        },
        {
          "title": "Ask a discriminating question",
          "paragraphs": [
            "A difference image subtracts images obtained during and outside the event and can locate the light that disappeared. A centroid measures the center of measured light; event-correlated motion is a source-location clue. Compare apertures and nearby catalog sources, and inspect quality flags and other stars for common instrumental behavior. These tests address causal alternatives that a folded flux curve alone cannot resolve. A failed diagnostic and an unavailable diagnostic must be recorded differently."
          ]
        }
      ],
      "example": {
        "title": "A binary hidden in plain sight",
        "steps": [
          "A neighboring star contributes 2% of the total aperture flux.",
          "Half its light disappears in a stellar eclipse.",
          "The total aperture loses 0.02 × 0.5 = 0.01 of its flux."
        ],
        "answer": "The apparent 1% dip could resemble a giant-planet transit on the target, while actually originating on the neighbor."
      },
      "project": "The 23 September TIC 150428135 teaching dossier has useful flux checks and catalog matches but lacks complete pixel-level source attribution. “Unmatched” therefore leaves both new-planet and non-planet explanations open.",
      "sources": [
        "crowd",
        "dave"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "A neighbor contributes 1% of total light and loses 50% of its own light. What is the observed depth in percent?",
          "answer": 0.5,
          "tolerance": 0.001,
          "unit": "%",
          "explanation": "0.01 × 0.5 = 0.005 of total light, or 0.5%.",
          "id": "impostors-q1",
          "lesson": "impostors"
        },
        {
          "type": "number",
          "prompt": "If constant contamination is 50% of total flux and observed depth is 200 ppm, what is the undiluted target depth?",
          "answer": 400,
          "tolerance": 0.1,
          "unit": "ppm",
          "explanation": "δtrue = δobs/(1 − c) = 200/0.5 = 400 ppm, assuming the target is the source.",
          "id": "impostors-q2",
          "lesson": "impostors"
        },
        {
          "type": "single",
          "prompt": "Which test most directly helps locate the source of a dip?",
          "options": [
            "An in-minus-out difference image",
            "A higher CNN score",
            "A longer object name",
            "Changing the train/test random seed"
          ],
          "answer": 0,
          "explanation": "Difference imaging seeks the pixels where flux disappeared.",
          "id": "impostors-q3",
          "lesson": "impostors"
        },
        {
          "type": "multi",
          "prompt": "Which observations merit investigating a stellar binary interpretation?",
          "options": [
            "Alternating event depths differ significantly",
            "A strong secondary eclipse",
            "Source motion toward a nearby variable star during the event",
            "A shallow dip by itself proves a binary"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The first three are relevant clues. Shallow depth alone is compatible with several causes.",
          "id": "impostors-q4",
          "lesson": "impostors"
        },
        {
          "type": "single",
          "prompt": "The centroid diagnostic is unavailable. How should the report describe it?",
          "options": [
            "Not assessed",
            "Passed",
            "Failed with certainty",
            "Planet confirmed"
          ],
          "answer": 0,
          "explanation": "Missing evidence cannot be converted into a passed test.",
          "id": "impostors-q5",
          "lesson": "impostors"
        },
        {
          "type": "single",
          "prompt": "Why is a U-shaped transit insufficient for validation?",
          "options": [
            "Other astrophysical configurations can produce a similar shape.",
            "Only V-shaped events can be planets.",
            "The flux axis must be logarithmic.",
            "All binaries are deeper than 50%."
          ],
          "answer": 0,
          "explanation": "Blending and geometry create overlapping light-curve shapes.",
          "id": "impostors-q6",
          "lesson": "impostors"
        }
      ],
      "lab": "transit",
      "code": null,
      "takeaway": "Vetting compares plausible causes of the same dip. Dilution can make a deep eclipse on a faint neighbor look like a shallow transit.",
      "pitfall": "Shape and depth alone do not securely identify the host or the cause. Use evidence that distinguishes the competing explanations.",
      "prerequisite": "missions"
    },
    {
      "id": "arrays",
      "unit": "search",
      "order": 5,
      "title": "Python arrays: the language of light curves",
      "hook": "Understand what a row, mask and tensor mean so you can read the project’s code instead of memorizing commands.",
      "minutes": 35,
      "objectives": [
        "Predict array shapes and masks.",
        "Keep times, flux and errors aligned.",
        "Distinguish missing values from physical zeros."
      ],
      "sections": [
        {
          "title": "Think in aligned columns",
          "paragraphs": [
            "Think of a light curve as a spreadsheet where each row is one observation. The time, flux, uncertainty and quality flag on that row belong together. A NumPy array stores a column of numbers so you can calculate with many rows at once. The key rule is alignment: if you remove the fifth flux value, also remove the fifth time, uncertainty and flag. Otherwise, the arrays can still have plausible values while describing observations that never occurred. Keep their lengths equal and use one shared selection mask whenever you filter the rows."
          ]
        },
        {
          "title": "Boolean masks select measurements",
          "paragraphs": [
            "A Boolean mask is an array of True/False values. Applying the same mask to time, flux and errors selects matching rows. For example, np.isfinite(flux) excludes NaN and infinite values. Combine masks with & and parenthesize comparisons. If you sort by time, apply the sorting index to every associated column. Filtering only flux silently pairs measurements with the wrong timestamps.",
            "Vectorization applies an operation to an entire array. flux / np.median(flux) normalizes each value using one reference. Broadcasting allows compatible shapes to combine, but can also create an unintended matrix. Check shapes before training, not after a suspicious metric appears."
          ]
        },
        {
          "title": "Missing does not mean dark",
          "paragraphs": [
            "NaN means a value is unavailable or undefined. Zero flux describes a physical or encoded number, not necessarily a missing measurement. Zero-padding a model input is a convention that must match training. A padding mask can tell a model which positions contain observations. A gap-filled curve may look continuous while the telescope observed nothing there.",
            "A tensor generalizes an array to multiple dimensions. A batch dimension groups examples for efficient model computation. NumPy typically handles preprocessing on a CPU; PyTorch tensors can also live on a GPU. Device changes do not fix incorrect units, masks or indexing."
          ]
        }
      ],
      "example": {
        "title": "One mask, three aligned arrays",
        "steps": [
          "time = [1, 2, 3]; flux = [1.0, NaN, 0.99]; errors = [0.01, 0.02, 0.01].",
          "A finite-flux mask is [True, False, True].",
          "Apply it to all columns: time becomes [1, 3], flux [1.0, 0.99], errors [0.01, 0.01]."
        ],
        "answer": "The remaining dip still belongs to time 3."
      },
      "project": "The saved shared_v1 record contains two three-channel arrays and seven scalar values. Correct shape alone is insufficient: each channel, ordering and unit must match training.",
      "sources": [
        "numpy",
        "lightkurve"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "How many scalar entries are in an array with shape (200, 3)?",
          "answer": 600,
          "tolerance": 0,
          "unit": "entries",
          "explanation": "Multiply the dimensions: 200 × 3 = 600.",
          "id": "arrays-q1",
          "lesson": "arrays"
        },
        {
          "type": "single",
          "prompt": "You remove bad flux rows. What must happen to time and errors?",
          "options": [
            "Apply the identical row mask.",
            "Leave both unchanged.",
            "Sort each independently.",
            "Replace every error with zero."
          ],
          "answer": 0,
          "explanation": "All columns must remain aligned by exposure.",
          "id": "arrays-q2",
          "lesson": "arrays"
        },
        {
          "type": "single",
          "prompt": "What does NaN usually represent here?",
          "options": [
            "An unavailable or undefined numerical value",
            "A measured zero brightness",
            "A confirmed non-transit",
            "A perfectly precise observation"
          ],
          "answer": 0,
          "explanation": "NaN is a missing/undefined-value marker, not a physical measurement.",
          "id": "arrays-q3",
          "lesson": "arrays"
        },
        {
          "type": "multi",
          "prompt": "Which checks can catch an input-contract error?",
          "options": [
            "Array dimensions",
            "Feature order and units",
            "Finite values and padding convention",
            "Only the filename extension"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "File type alone does not establish the meaning or validity of the stored numbers.",
          "id": "arrays-q4",
          "lesson": "arrays"
        },
        {
          "type": "number",
          "prompt": "A batch has shape (32, 100, 3). How many individual examples are in the batch?",
          "answer": 32,
          "tolerance": 0,
          "unit": "examples",
          "explanation": "The first dimension is the batch size in this stated layout.",
          "id": "arrays-q5",
          "lesson": "arrays"
        },
        {
          "type": "single",
          "prompt": "Why is sorting flux independently from time invalid?",
          "options": [
            "It destroys the time-to-measurement association.",
            "Sorted values cannot be stored in Python.",
            "The mean must become zero.",
            "It changes the stellar radius."
          ],
          "answer": 0,
          "explanation": "Temporal structure is encoded by paired time and flux, not separate sorted lists.",
          "id": "arrays-q6",
          "lesson": "arrays"
        }
      ],
      "lab": null,
      "code": "import numpy as np\ntime = np.array([1., 2., 3.])\nflux = np.array([1., np.nan, .99])\nerror = np.array([.01, .02, .01])\ngood = np.isfinite(time) & np.isfinite(flux) & np.isfinite(error)\ntime, flux, error = time[good], flux[good], error[good]\nassert time.tolist() == [1., 3.]\nprint(flux / np.median(flux))",
      "takeaway": "Treat time, flux, uncertainty and flags as aligned columns. A shared mask keeps each measurement attached to the right timestamp.",
      "pitfall": "Replacing missing flux with zero invents a very deep dip. Preserve missingness or exclude the row under a documented rule.",
      "prerequisite": "impostors"
    },
    {
      "id": "clean",
      "unit": "search",
      "order": 6,
      "title": "Cleaning without erasing the signal",
      "hook": "A perfectly smooth light curve is useless if the cleaning step removed the transits you wanted to find.",
      "minutes": 35,
      "objectives": [
        "Explain quality filtering and time systems.",
        "Choose a sensible detrending timescale.",
        "Recognize uncertainty and injection requirements."
      ],
      "sections": [
        {
          "title": "Open the metadata before fitting",
          "paragraphs": [
            "Before you smooth a light curve, find out what its numbers mean. Read the time units and zero point, the flux column, the uncertainty column and the quality flags. Decide which flags your analysis will exclude and record that choice. A time value without its time system is incomplete information: using the wrong zero point can put a real transit at the wrong predicted time. Likewise, different flux columns can include different corrections. Start by plotting the original data with gaps and flagged points visible, so you can later see what your cleaning changed.",
            "Quality flags encode events or conditions with bits; “nonzero” is not a universal prescription to discard everything. Record the chosen bit mask and reason. Retain raw files so a later policy change is reproducible."
          ]
        },
        {
          "title": "Separate slow trends from brief dips",
          "paragraphs": [
            "Detrending estimates slow variability or instrumental drift and removes it, often by dividing flux by a trend model. Median filters, splines and Gaussian processes make different smoothness assumptions. A window too short can absorb a transit; a window too long can leave variable-star structure that triggers the search. Mask known or proposed transit intervals when refining a trend, and check sensitivity to reasonable choices.",
            "Simple sigma clipping removes extreme outliers relative to a location and scale. Aggressive symmetric clipping may delete the deepest in-transit samples. Instrumental spikes and genuine transits both depart from baseline; a threshold alone does not identify the cause."
          ]
        },
        {
          "title": "Propagate the meaning of the transformation",
          "paragraphs": [
            "Dividing flux by a known constant k also divides its uncertainty by |k|. If k is estimated from the data, its uncertainty and induced correlations may matter. A trend fit can correlate residuals and distort event depth. Keep original times and gap boundaries; interpolated points do not become additional independent observations.",
            "The strongest practical test is to inject a synthetic transit before detrending and see whether the entire pipeline recovers it. Injecting afterward tests only later stages and cannot reveal signal loss caused by cleaning."
          ]
        },
        {
          "title": "A completed test still has assumptions",
          "paragraphs": [
            "The physical benchmark now adds limb-darkened circular transits to archival observations, distributing their signal across pixels with an empirical static point-spread function (PSF). Sending these injections through cleaning can expose lost sensitivity. Assumed stellar density, fixed limb-darkening coefficients and a static PSF simplify the sky; they do not cover every systematic or eclipsing blend. The fresh 99-host recovery study changes search and calibration, not neural weights."
          ]
        }
      ],
      "example": {
        "title": "The transit-eating filter",
        "steps": [
          "A transit lasts 3 hours.",
          "A flexible trend fitted on a 1-hour scale can follow the dip itself.",
          "Flattening by this trend can make the transit much shallower."
        ],
        "answer": "Compare recovery with a longer trend scale and transit masking; the best-looking residual plot is not sufficient."
      },
      "project": "The watcher’s detrending and detection settings belong in the run evidence. The original tiny injection pilot was a smoke test. Completed 90-host physical and 99-host fresh recovery studies now test injected signals through cleaning and search, with remaining weak-signal and contamination limits.",
      "sources": [
        "lightkurve",
        "tess"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "Where should a realistic transit be injected to measure detrending losses?",
          "options": [
            "Before detrending",
            "Only after the final CNN score",
            "Only into a catalog label",
            "After all quality cuts without documenting them"
          ],
          "answer": 0,
          "explanation": "The synthetic signal must pass through any stage whose loss you want to measure.",
          "id": "clean-q1",
          "lesson": "clean"
        },
        {
          "type": "number",
          "prompt": "Flux and its error are divided by a fixed 200. An original error is 4 flux units. What is the new error?",
          "answer": 0.02,
          "tolerance": 1e-05,
          "unit": "relative flux",
          "explanation": "4 / 200 = 0.02, treating the divisor as fixed.",
          "id": "clean-q2",
          "lesson": "clean"
        },
        {
          "type": "multi",
          "prompt": "What belongs in a reproducible cleaning record?",
          "options": [
            "Time reference and units",
            "Quality-bit policy",
            "Detrending method and settings",
            "Only a screenshot of the final curve"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "A screenshot does not specify the transformation applied to the raw measurements.",
          "id": "clean-q3",
          "lesson": "clean"
        },
        {
          "type": "single",
          "prompt": "What risk comes from very aggressive downward sigma clipping?",
          "options": [
            "Removing real in-transit measurements",
            "Making timestamps more accurate",
            "Measuring the planet’s mass",
            "Guaranteeing independent residuals"
          ],
          "answer": 0,
          "explanation": "Transit measurements are below the baseline and may be mistaken for outliers.",
          "id": "clean-q4",
          "lesson": "clean"
        },
        {
          "type": "single",
          "prompt": "Why should gaps remain explicit?",
          "options": [
            "Interpolated points are not independent telescope measurements.",
            "Gaps imply a stellar eclipse.",
            "Every gap is exactly one orbital period.",
            "Neural networks never accept masks."
          ],
          "answer": 0,
          "explanation": "Invented samples can create false coverage and overstate precision.",
          "id": "clean-q5",
          "lesson": "clean"
        },
        {
          "type": "single",
          "prompt": "Two files both contain time = 1500. Can their events be aligned directly?",
          "options": [
            "Only after checking reference zero points and time systems",
            "Always, because the numbers match",
            "Never, even with metadata",
            "Only if their CNN scores match"
          ],
          "answer": 0,
          "explanation": "The number has meaning only together with its time convention.",
          "id": "clean-q6",
          "lesson": "clean"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Cleaning changes the data that the search will see. Compare before and after, and test whether your chosen treatment preserves transit signals.",
      "pitfall": "A smoother that follows the transit can divide it away. A visually tidy light curve is not necessarily a scientifically better one.",
      "prerequisite": "arrays"
    },
    {
      "id": "fold",
      "unit": "search",
      "order": 7,
      "title": "Folding and BLS: search before classification",
      "hook": "A folded curve can look compelling at the wrong period. Learn how that picture was constructed.",
      "minutes": 35,
      "objectives": [
        "Calculate phase from an ephemeris.",
        "Explain what BLS searches over.",
        "Separate detection statistics from model scores."
      ],
      "sections": [
        {
          "title": "Fold time onto one cycle",
          "paragraphs": [
            "Suppose a planet transits every five days. You can compare its repeated events by putting each measurement at its position within a five-day cycle. That operation is phase folding. First subtract the reference time t₀; then divide by the trial period P. The fractional part, ((t − t₀)/P) mod 1, is a phase between 0 and 1. Times separated by exactly one period land at the same phase. For a transit-centered plot, phase is often wrapped to −0.5 through 0.5. Folding is useful because repeated dips can line up, but the alignment depends on the period and epoch you chose."
          ]
        },
        {
          "title": "BLS is a search over hypotheses",
          "paragraphs": [
            "Box Least Squares approximates a transit as a box-shaped decrease in flux. At trial periods, durations and event times, it finds how much better a transit model fits than a constant baseline under its objective. A periodogram plots a search statistic against period or frequency. The highest peak is the best of the tried hypotheses, not automatically a planet or the true period.",
            "A period grid that is too coarse can smear a shallow transit across the baseline. Searching more durations and epochs changes the number of opportunities for noise to fit. The selection rule and grid are therefore part of the experiment, not cosmetic plotting choices."
          ]
        },
        {
          "title": "Detection and classification are different tasks",
          "paragraphs": [
            "A catalog-folded classifier receives an already estimated period and centered signal. A blind detector must find that period or identify events without one. Excellent classification of prepared, correctly folded examples does not establish blind-search completeness. An estimated signal-to-noise ratio, a BLS likelihood statistic and a CNN sigmoid output describe different quantities. Never compare them as if each were a calibrated probability."
          ]
        }
      ],
      "example": {
        "title": "Fold three times by hand",
        "steps": [
          "Use P = 5 days and t₀ = 2 days.",
          "Times 2, 7 and 12 yield (t − t₀)/P = 0, 1 and 2.",
          "Taking the fractional part puts all three at phase 0."
        ],
        "answer": "Repeated events line up. At the wrong period, they can spread out or align only at an alias."
      },
      "project": "The operational watcher uses BLS proposals (0.5–30 days, six trial durations, up to three signals per light curve). Offline detector BLS/TLS benchmarks use their own locked protocol and control calibration. The legacy bls_snr input is BLS power, not a physical SNR.",
      "sources": [
        "bls"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "For t = 9 days, t₀ = 2 days and P = 5 days, calculate phase in [0, 1).",
          "answer": 0.4,
          "tolerance": 0.0001,
          "unit": "phase",
          "explanation": "(9 − 2)/5 = 1.4; the fractional part is 0.4.",
          "id": "fold-q1",
          "lesson": "fold"
        },
        {
          "type": "single",
          "prompt": "What does BLS primarily search for?",
          "options": [
            "A repeating box-like reduction in flux across trial ephemerides",
            "A spectroscopic mass measurement",
            "The best planet name",
            "A calibrated probability for each star"
          ],
          "answer": 0,
          "explanation": "The search compares trial box-transit fits to the measured series.",
          "id": "fold-q2",
          "lesson": "fold"
        },
        {
          "type": "multi",
          "prompt": "What can phase folding hide?",
          "options": [
            "Differences between individual transits",
            "Which cycles had missing data",
            "Timing variations",
            "The need for an input trial period"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Stacking can conceal temporal context. A fold still requires a period, so it cannot hide that methodological requirement.",
          "id": "fold-q3",
          "lesson": "fold"
        },
        {
          "type": "single",
          "prompt": "A model performs well on correctly catalog-folded transits. What still needs separate evaluation?",
          "options": [
            "Blind detection and period recovery",
            "Whether multiplication works",
            "Whether Python can read strings",
            "Whether a plot has axes"
          ],
          "answer": 0,
          "explanation": "Prepared classification assumes upstream knowledge that a blind survey must recover.",
          "id": "fold-q4",
          "lesson": "fold"
        },
        {
          "type": "single",
          "prompt": "A periodogram has a highest peak. What can be concluded?",
          "options": [
            "It is best among the hypotheses tried under that statistic.",
            "Its false-alarm probability is zero.",
            "The planet is confirmed.",
            "All other periods are impossible."
          ],
          "answer": 0,
          "explanation": "Grid choice, aliases and noise can produce a highest peak without a secure physical solution.",
          "id": "fold-q5",
          "lesson": "fold"
        },
        {
          "type": "number",
          "prompt": "At P = 4 days, how many orbital cycles span 20 days?",
          "answer": 5,
          "tolerance": 0,
          "unit": "cycles",
          "explanation": "20/4 = 5 cycles, before considering phase and actual observing coverage.",
          "id": "fold-q6",
          "lesson": "fold"
        }
      ],
      "lab": "fold",
      "code": null,
      "takeaway": "Folding aligns measurements under a proposed ephemeris. BLS searches trial ephemerides for box-shaped dips; the classifier then scores a proposed event.",
      "pitfall": "A neat fold depends on the period you assumed. Always return to individual events before accepting that period.",
      "prerequisite": "clean"
    },
    {
      "id": "aliases",
      "unit": "search",
      "order": 8,
      "title": "Aliases, TLS and the search budget",
      "hook": "The strongest peak can be half the orbit, twice the orbit, or a pattern produced by the observing window.",
      "minutes": 35,
      "objectives": [
        "Compare BLS and transit-shaped searches.",
        "Test harmonic periods and timing predictions.",
        "Understand trial counts and empirical false alarms."
      ],
      "sections": [
        {
          "title": "Why several periods can fit",
          "paragraphs": [
            "Imagine seeing two dips with a long gap between them. They might be consecutive transits, or you might have missed one or more intervening events. The resulting possible periods are aliases: different timing solutions that can explain the available observations. A search can also choose half the true period when two similar eclipses occur during each orbit, or twice the true period when alternating events differ. To investigate, draw the predicted event times on the original light curve. A predicted dip with no data at that time remains untested; a well-observed interval with no dip provides useful evidence."
          ]
        },
        {
          "title": "Choose the template for the question",
          "paragraphs": [
            "BLS uses a box approximation. Transit Least Squares uses transit-shaped templates with more physical structure, including ingress, egress and limb darkening. Such templates can help with small transit signals, but a better template does not remove contamination, incorrect stellar assumptions or search-selection bias. Benchmark detection recovery, false alarms and compute cost using the same targets and preprocessing. TLS is a published method to compare, not a currently implemented option in this watcher."
          ]
        },
        {
          "title": "A large search gets many chances to be fooled",
          "paragraphs": [
            "If N independent null trials each exceed a threshold with probability p, the expected number of exceedances is Np. The probability of at least one is 1 − (1 − p)^N. Real period trials are correlated, so the count of grid points is not a reliable count of independent trials. These formulas build intuition; estimate practical false alarms with representative null light curves and the full search process.",
            "A white-noise SNR threshold from one survey does not inherit its reliability when copied into another pipeline. Gaps, correlated noise and repeated signal subtraction all affect the tail of the detection statistic. Lock the search settings before final evaluation."
          ]
        }
      ],
      "example": {
        "title": "A seemingly tiny false-alarm probability",
        "steps": [
          "Imagine 100,000 stars with 100 independent trials each.",
          "There are 10,000,000 null opportunities.",
          "At p = 0.000001, the expected number of exceedances is 10."
        ],
        "answer": "A tiny per-trial probability can still produce numerous false alerts. Correlated real searches require empirical evaluation."
      },
      "project": "The historical TIC 150428135 case remains an alias exercise, not a current ranking claim. Offline BLS/TLS physical-injection comparisons now exist, but their inverted controls still cannot assign a survey-wide false-alarm rate.",
      "sources": [
        "tls",
        "bls"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "With 100,000 independent null trials and per-trial exceedance probability 0.00001, how many false exceedances are expected?",
          "answer": 1,
          "tolerance": 0.0001,
          "unit": "expected exceedances",
          "explanation": "Np = 100000 × 0.00001 = 1. This is an expectation, not a guaranteed count.",
          "id": "aliases-q1",
          "lesson": "aliases"
        },
        {
          "type": "single",
          "prompt": "What distinguishes TLS from standard BLS?",
          "options": [
            "More transit-shaped templates",
            "Automatic proof that every signal is a planet",
            "No need to search periods",
            "A guarantee of zero computation cost"
          ],
          "answer": 0,
          "explanation": "Template realism can help search sensitivity but does not settle false-positive hypotheses.",
          "id": "aliases-q2",
          "lesson": "aliases"
        },
        {
          "type": "multi",
          "prompt": "What should an alias investigation compare?",
          "options": [
            "Predicted event times against observed coverage",
            "Individual event depths and durations",
            "P/2, P and 2P where applicable",
            "Only the tallest plotted peak"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The full event pattern matters; the largest peak alone cannot rule out aliases.",
          "id": "aliases-q3",
          "lesson": "aliases"
        },
        {
          "type": "single",
          "prompt": "Can the number of trial periods be treated as the number of independent statistical tests?",
          "options": [
            "Generally no; nearby trials are correlated.",
            "Always, by definition.",
            "Only if the plot uses a log axis.",
            "It equals the number of planets."
          ],
          "answer": 0,
          "explanation": "Nearby templates often reuse almost the same measurements and overlap strongly.",
          "id": "aliases-q4",
          "lesson": "aliases"
        },
        {
          "type": "single",
          "prompt": "Which comparison is fairest for a new search method?",
          "options": [
            "Same targets, preprocessing and evaluation rules; measure recovery, false alarms and runtime.",
            "Different easy targets for the new method",
            "Only training accuracy",
            "The most attractive example plot"
          ],
          "answer": 0,
          "explanation": "A controlled comparison isolates the method rather than changing the evaluation problem.",
          "id": "aliases-q5",
          "lesson": "aliases"
        },
        {
          "type": "single",
          "prompt": "A 7.1 white-noise SNR cut passes a candidate. What is justified?",
          "options": [
            "It passes that stated diagnostic threshold.",
            "It has a 99.999% planet probability.",
            "Every correlated-noise scenario is excluded.",
            "It is ready for confirmation."
          ],
          "answer": 0,
          "explanation": "A threshold on one statistic does not supply population-calibrated reliability.",
          "id": "aliases-q6",
          "lesson": "aliases"
        }
      ],
      "lab": "trials",
      "code": null,
      "takeaway": "Several periods can explain incomplete or alternating events. A larger search also creates more opportunities for noise to look interesting.",
      "pitfall": "The strongest periodogram peak is a hypothesis to check, not a guarantee that you found the orbital period.",
      "prerequisite": "fold"
    },
    {
      "id": "noise",
      "unit": "statistics",
      "order": 9,
      "title": "Noise, likelihood and uncertainty",
      "hook": "A tiny error bar can be misleading if the measurements share the same systematic error.",
      "minutes": 35,
      "objectives": [
        "Calculate a simple white-noise transit SNR.",
        "Distinguish uncertainty from bias.",
        "Interpret likelihood and a confidence interval."
      ],
      "sections": [
        {
          "title": "Random scatter and systematic error differ",
          "paragraphs": [
            "Start by asking what makes repeated brightness measurements differ. Photon-counting and detector noise contribute scatter. A systematic effect, such as changing spacecraft behavior or an imperfect trend correction, can move many neighboring points together. We call time-correlated noise red noise. In a likelihood, you specify how probable the observed measurements would be under a proposed signal and noise model. If you assume independent Gaussian errors, each point contributes as though its error were unrelated to the others. That can make uncertainty look too small when nearby errors actually move together. The noise assumptions are part of the calculation."
          ]
        },
        {
          "title": "Where the square-root rule comes from",
          "paragraphs": [
            "If n independent measurements each have standard deviation σ, the standard error of their mean is σ/√n. A simple transit-depth signal-to-noise estimate is SNR ≈ δ√n/σ, treating the out-of-transit baseline as well known. δ and σ must use the same units. Correlation reduces the effective independent sample size, and uncertainty in the baseline or fitted parameters adds complexity.",
            "For Gaussian independent errors, a model’s log likelihood contains −½Σ[(fi − mi)/σi]² plus normalization terms. Here fi is observed flux and mi is modeled flux. A likelihood compares how compatible the data are with specified parameters; it is not by itself a probability distribution over those parameters."
          ]
        },
        {
          "title": "Intervals need an interpretation",
          "paragraphs": [
            "A frequentist 95% confidence interval comes from a procedure that covers the true parameter in 95% of repeated experiments under its assumptions. A Bayesian credible interval contains a stated posterior mass under a model and prior. Neither interpretation rescues a misspecified model.",
            "A bootstrap resamples data to approximate variability in a statistic. If several measurements share one star, resampling rows independently can exaggerate precision. Resample independent groups or preserve time blocks when the dependence structure requires it. Report the sample size and resampling unit alongside the interval."
          ]
        }
      ],
      "example": {
        "title": "A tempting SNR calculation",
        "steps": [
          "Depth = 200 ppm; per-point scatter = 400 ppm; n = 100 independent in-transit samples.",
          "SNR ≈ 200 × √100 / 400 = 5.",
          "If only 25 samples are effectively independent, the same estimate falls to 2.5."
        ],
        "answer": "The independence assumption can matter as much as the number of samples."
      },
      "project": "The blind report’s white-noise-only SNR is a diagnostic. It is not an empirically calibrated false-alarm probability, and the model input named bls_snr is a different legacy statistic.",
      "sources": [
        "bls"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "Depth is 300 ppm, per-point scatter 600 ppm and n=100 independent in-transit samples. What is the simplified SNR?",
          "answer": 5,
          "tolerance": 0.001,
          "unit": "SNR",
          "explanation": "300 × √100 / 600 = 5.",
          "id": "noise-q1",
          "lesson": "noise"
        },
        {
          "type": "number",
          "prompt": "Independent measurements have σ=20 and n=25. What is the standard error of their mean?",
          "answer": 4,
          "tolerance": 0.001,
          "unit": "same units as measurement",
          "explanation": "20/√25 = 4.",
          "id": "noise-q2",
          "lesson": "noise"
        },
        {
          "type": "single",
          "prompt": "What happens when correlated samples are incorrectly treated as independent?",
          "options": [
            "Uncertainty can be underestimated.",
            "The stellar radius becomes exact.",
            "The number of real observations increases.",
            "All noise becomes Gaussian."
          ],
          "answer": 0,
          "explanation": "Shared fluctuations contribute less independent information than the row count suggests.",
          "id": "noise-q3",
          "lesson": "noise"
        },
        {
          "type": "single",
          "prompt": "What is a likelihood?",
          "options": [
            "Data compatibility as a function of specified model parameters",
            "Automatically a planet posterior",
            "The frequency of planets in the Galaxy",
            "The CNN’s training-set size"
          ],
          "answer": 0,
          "explanation": "A prior and normalization are needed to turn a likelihood into a Bayesian posterior over hypotheses.",
          "id": "noise-q4",
          "lesson": "noise"
        },
        {
          "type": "multi",
          "prompt": "Which belong in an uncertainty report?",
          "options": [
            "Sample size",
            "Independence or grouping assumptions",
            "Interval construction method",
            "Only the best random seed"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The sampling and interval procedure determine what uncertainty means.",
          "id": "noise-q5",
          "lesson": "noise"
        },
        {
          "type": "single",
          "prompt": "Repeated measurements share an incorrect stellar radius. What happens to the radius bias as you add flux points?",
          "options": [
            "It can persist despite smaller photometric scatter.",
            "It must disappear as 1/√n.",
            "It becomes a catalog match.",
            "It turns into a period alias."
          ],
          "answer": 0,
          "explanation": "More data under the same incorrect host assumption do not fix the systematic radius error.",
          "id": "noise-q6",
          "lesson": "noise"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "The familiar square-root improvement assumes independent information. Correlated measurements contain less new information than the same number of independent points.",
      "pitfall": "More samples do not automatically justify a tighter interval. Check the noise assumptions behind the interval or SNR.",
      "prerequisite": "aliases"
    },
    {
      "id": "metrics",
      "unit": "statistics",
      "order": 10,
      "title": "Confusion matrices and the rare-planet problem",
      "hook": "A classifier can be 99% accurate and still waste most of your follow-up time.",
      "minutes": 35,
      "objectives": [
        "Calculate precision, recall and false-positive rate.",
        "Distinguish ranking metrics from threshold metrics.",
        "Connect prevalence to follow-up workload."
      ],
      "sections": [
        {
          "title": "Count decisions before interpreting percentages",
          "paragraphs": [
            "Choose a score threshold and imagine labeling every signal above it as an alert. There are four possible outcomes. A true positive is an alert on a real positive; a false positive is an alert on a negative. A false negative is a positive you missed, and a true negative is a negative you correctly rejected. Recall, also called sensitivity, is TP/(TP+FN): the fraction of positives you found. Precision is TP/(TP+FP): the fraction of your alerts that are positives. The false-positive rate is FP/(FP+TN). Write down the denominator before interpreting any percentage; these metrics answer different questions."
          ]
        },
        {
          "title": "The base rate changes the alert list",
          "paragraphs": [
            "Prevalence is the fraction of genuine positives in the evaluated population. For sensitivity s, false-positive rate f and prevalence π, expected alert precision is sπ / [sπ + f(1−π)]. When genuine positives are rare, a small false-positive rate can still generate many more false alerts than true ones. Class balancing during training does not set the prevalence of a blind search.",
            "A practical objective can be recall at a fixed vetting budget: how many true signals appear among the first K alerts? Report precision and workload together rather than choosing a threshold only because it is 0.5."
          ]
        },
        {
          "title": "Ranking does not supply a probability",
          "paragraphs": [
            "ROC-AUC measures discrimination across thresholds and can be interpreted through the ordering of positive-negative pairs. A precision–recall curve emphasizes the positive class. Average precision (AP) summarizes precision at increasing recall using its defined step-weighted calculation; it is not simply accuracy or the mean predicted probability.",
            "AP depends on labels and prevalence. Comparing AP from different target populations, labeling rules or data splits is not a controlled model comparison. Specify the same held-out examples and uncertainty for paired comparisons."
          ]
        },
        {
          "title": "Perfect ranking can still miss positives",
          "paragraphs": [
            "Static v4 placed all three fresh positive candidates above all eleven negatives, giving AP and ROC AUC of 1.0. At threshold 0.5 it selected only one positive, so two positives were missed and accuracy was 12/14. The nonlinear stack selected two positives with no false positives: 13/14 correct, despite worse ranking (AP 0.833333). A threshold decides which cases are selected; AP summarizes their ordering across thresholds. With only three positives, neither number establishes a general winner."
          ]
        }
      ],
      "example": {
        "title": "One thousand alerts from a mostly negative sky",
        "steps": [
          "Among 100,000 signals, 100 are true positives in the population.",
          "At 95% sensitivity: 95 true alerts. At 1% false-positive rate: 999 false alerts.",
          "Precision = 95/(95+999) ≈ 8.68%."
        ],
        "answer": "Excellent-looking sensitivity and specificity still yield an alert list dominated by false positives."
      },
      "project": "On the fresh 14-candidate audit (3 positive, 11 negative), static v4 has AP/AUC 1.0 but 12/14 correct at 0.5. The nonlinear stack has AP 0.833333, AUC 0.909091 and 13/14 correct. Ranking, threshold accuracy and planet confirmation are different claims.",
      "sources": [
        "cal"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "An alert list contains TP=30 and FP=10. What is precision in percent?",
          "answer": 75,
          "tolerance": 0.01,
          "unit": "%",
          "explanation": "30/(30+10) = 0.75 = 75%.",
          "id": "metrics-q1",
          "lesson": "metrics"
        },
        {
          "type": "number",
          "prompt": "A labeled sample has TP=30 and FN=20. What is recall in percent?",
          "answer": 60,
          "tolerance": 0.01,
          "unit": "%",
          "explanation": "30/(30+20) = 0.60 = 60%.",
          "id": "metrics-q2",
          "lesson": "metrics"
        },
        {
          "type": "single",
          "prompt": "A survey contains 99% negative examples. A model predicts every example negative. Why is 99% accuracy inadequate?",
          "options": [
            "It finds none of the positives.",
            "It has perfect planet recall.",
            "It must be calibrated.",
            "It has proven every signal false."
          ],
          "answer": 0,
          "explanation": "The classifier attains high accuracy through the majority class while recall is zero.",
          "id": "metrics-q3",
          "lesson": "metrics"
        },
        {
          "type": "multi",
          "prompt": "Which must be matched for a fair comparison of AP?",
          "options": [
            "Evaluation cohort",
            "Positive-label definition",
            "Data split and selection rules",
            "Website font"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "AP depends on the evaluated problem, not only the architecture.",
          "id": "metrics-q4",
          "lesson": "metrics"
        },
        {
          "type": "single",
          "prompt": "What does AP summarize?",
          "options": [
            "Ranking precision over recall increments",
            "The probability that the top candidate is a planet",
            "The percentage of observations with no gaps",
            "The stellar temperature distribution"
          ],
          "answer": 0,
          "explanation": "AP is an aggregate ranking statistic; it does not calibrate individual predictions.",
          "id": "metrics-q5",
          "lesson": "metrics"
        },
        {
          "type": "single",
          "prompt": "What happens to precision when prevalence falls but sensitivity and false-positive rate stay fixed?",
          "options": [
            "Precision decreases.",
            "Precision necessarily increases.",
            "Precision stays exactly fixed.",
            "Recall becomes undefined in every case."
          ],
          "answer": 0,
          "explanation": "More negatives relative to positives means false alerts occupy a larger fraction of the selected list.",
          "id": "metrics-q6",
          "lesson": "metrics"
        }
      ],
      "lab": "base-rate",
      "code": null,
      "takeaway": "Recall describes the positives you recover; precision describes the alerts you can trust. A rare positive class can make even a small false-positive rate costly.",
      "pitfall": "Do not read 99% specificity as 99% of alerts being planets. Those statements use different denominators.",
      "prerequisite": "noise"
    },
    {
      "id": "splits",
      "unit": "statistics",
      "order": 11,
      "title": "Leakage: the shortcut that breaks the experiment",
      "hook": "A split can contain different rows and still contain the same stars on both sides.",
      "minutes": 35,
      "objectives": [
        "Assign train, tuning, calibration and audit roles.",
        "Split by independent scientific units.",
        "Find leakage in preprocessing and repeated testing."
      ],
      "sections": [
        {
          "title": "Separate four jobs",
          "paragraphs": [
            "Think of evaluation as a sequence of increasingly protected decisions. Training data teach the weights. Validation data help you choose settings and a checkpoint. A separate calibration set can fit the mapping from scores to frequencies. An audit or test set assesses the procedure after those choices are fixed. If you repeatedly inspect audit results and change the method to improve them, the audit has become part of your tuning process. Its score no longer describes a completely untouched evaluation. Naming a file test.csv does not protect it; what matters is which decisions used its contents.",
            "A test set stops being untouched once its outcomes influence your method. Calling it “test” in a filename does not restore independence. Keep a decision log and reserve a fresh prospective or otherwise untouched audit for strong claims."
          ]
        },
        {
          "title": "Split entities, not just records",
          "paragraphs": [
            "Multiple sectors, alternate reductions, repeated candidates and augmented versions of one star can share distinctive signatures. If relatives cross a train/test boundary, a classifier may recognize the entity rather than generalize to a new star. Use star or related-system groups, reconcile identifiers across missions and handle nearby blended sources conservatively. A coordinate match can help identify duplicates, but a chosen angular tolerance is a policy requiring inspection, not proof that every association is correct."
          ]
        },
        {
          "title": "Fit transformations inside the training boundary",
          "paragraphs": [
            "A normalizer estimates means, standard deviations or other scales. If these are learned from all rows before splitting, held-out data influence the representation. Fit it on training data and apply the frozen transformation elsewhere. The same rule applies to imputation, feature selection and learned detrending when they borrow population information.",
            "Data augmentation creates modified training examples; it does not create independent test stars. Near-duplicate injections or transformations must remain tied to their source group. Random seeds make a chosen procedure repeatable, but cannot repair a scientifically invalid split."
          ]
        },
        {
          "title": "Cross-fitting protects one boundary, not every boundary",
          "paragraphs": [
            "To train a stack on expert predictions, divide training hosts into folds. Fit an expert without one fold, predict the omitted hosts, and repeat. Every training prediction then comes from an expert that did not train on that host. Otherwise a stack could learn from unrealistically easy in-sample expert scores.",
            "Our nonlinear model uses 538 out-of-fold rows, 162 selection rows for complexity and blend, 81 calibration rows and 82 audit rows. Host-disjoint cross-fitting protects stack training, but it cannot make a repeatedly consulted audit independent again. The later 14-candidate study froze all weights, preprocessing and calibration before new inference."
          ]
        }
      ],
      "example": {
        "title": "A deceptively clean 80/20 split",
        "steps": [
          "Star A has ten sectors, each stored as a separate row.",
          "Eight sectors enter training and two enter test.",
          "The model can exploit Star A’s recurring noise or contamination."
        ],
        "answer": "Split Star A as one group before creating sector-level examples or augmentations."
      },
      "project": "The reused 82-row classifier audit is development evidence. The frozen fresh check evaluates 14 available candidates from 295 registered; 281 lacked native 120-second public products. All 14 available passed unchanged preparation. Coverage selection is part of the result.",
      "sources": [
        "astro",
        "dann"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "Where should a data-dependent normalizer be fitted?",
          "options": [
            "Only on the allowed training partition",
            "On the whole dataset before splitting",
            "On the final audit labels",
            "On whichever split improves the score"
          ],
          "answer": 0,
          "explanation": "The transformation must not learn distributional information from held-out evaluation data.",
          "id": "splits-q1",
          "lesson": "splits"
        },
        {
          "type": "multi",
          "prompt": "Which records should ordinarily remain grouped?",
          "options": [
            "Different sectors of one star",
            "Augmented copies of an original example",
            "Duplicate cross-mission identities",
            "Unrelated stars merely because they have similar brightness"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Shared physical or derived identity creates dependence. Similar brightness alone does not imply identity.",
          "id": "splits-q2",
          "lesson": "splits"
        },
        {
          "type": "single",
          "prompt": "A researcher changes hyperparameters after seeing test performance. What is the consequence?",
          "options": [
            "That test has influenced selection and is no longer an untouched audit.",
            "The test becomes larger.",
            "The model becomes automatically unbiased.",
            "Renaming the file fixes the issue."
          ],
          "answer": 0,
          "explanation": "Selection on test outcomes consumes the independence of the test.",
          "id": "splits-q3",
          "lesson": "splits"
        },
        {
          "type": "single",
          "prompt": "What is the role of a calibration partition?",
          "options": [
            "Fit a score-to-probability mapping under a stated population",
            "Choose every architecture and report final accuracy on the same rows",
            "Store only negative examples",
            "Replace group identities"
          ],
          "answer": 0,
          "explanation": "Calibration is a learned step and needs separation from final evaluation.",
          "id": "splits-q4",
          "lesson": "splits"
        },
        {
          "type": "number",
          "prompt": "An audit contains 82 rows from 79 groups. How many independent groups are stated?",
          "answer": 79,
          "tolerance": 0,
          "unit": "groups",
          "explanation": "The group count is 79. The 82 rows are not automatically 82 independent stars.",
          "id": "splits-q5",
          "lesson": "splits"
        },
        {
          "type": "single",
          "prompt": "Does fixing a random seed prevent leakage?",
          "options": [
            "No; it only makes the chosen procedure more repeatable.",
            "Yes, provided the seed is 42.",
            "Yes, for all CNNs.",
            "Only when using a GPU."
          ],
          "answer": 0,
          "explanation": "Reproducibility and validity are separate properties.",
          "id": "splits-q6",
          "lesson": "splits"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Separate examples according to the scientific claim. To assess performance on unseen stars, keep related observations of a star together across the split.",
      "pitfall": "Changing the model after seeing audit performance uses audit information. A renamed file cannot make those examples untouched again.",
      "prerequisite": "metrics"
    },
    {
      "id": "probability",
      "unit": "statistics",
      "order": 12,
      "title": "Scores, calibration and Bayesian evidence",
      "hook": "“What is its probability?” requires a defined population and competing explanations, not another decimal place.",
      "minutes": 35,
      "objectives": [
        "Distinguish sigmoid output, calibration and validation.",
        "Apply Bayes’ rule to a small example.",
        "Explain reliability diagrams and temperature scaling."
      ],
      "sections": [
        {
          "title": "A number between zero and one is not enough",
          "paragraphs": [
            "Seeing a score of 0.8 makes it tempting to say “an 80% chance of a planet.” A sigmoid output does not justify that interpretation by itself. Calibration asks a specific, testable question: among comparable examples assigned scores near 0.8, are about 80% positive? Check that relationship on data held out from fitting the model and any calibration mapping. A model can rank planets above impostors quite well while giving misleading numerical confidence. That is why ranking quality and calibration need separate measurements, even when both use the same predictions.",
            "Reliability diagrams compare average predicted confidence with observed positive frequency in bins. Sample size and bin choices matter. Brier score averages (s−y)²; log loss penalizes confident mistakes strongly. Evaluate calibration separately from discrimination."
          ]
        },
        {
          "title": "Calibration has a scope",
          "paragraphs": [
            "Temperature scaling learns a positive T and uses sigmoid(z/T) for binary logits. A positive scalar temperature preserves ranking but changes confidence. Fit T on calibration data and evaluate it on other appropriate data. A calibrator trained on prepared catalog signals need not work for noisy, blind-search proposals. Changes in prevalence, covariates or label meaning can invalidate the transfer. Ensembles and seed agreement are useful diagnostics, not automatic probability certificates."
          ]
        },
        {
          "title": "Bayes compares explicit alternatives",
          "paragraphs": [
            "Bayes’ rule multiplies prior probabilities by likelihoods and normalizes across hypotheses. In odds form, posterior odds = prior odds × likelihood ratio. A planet-versus-binary calculation needs astrophysical alternatives, population priors, selection effects and relevant observations. Statistical validation estimates whether plausible false-positive scenarios are sufficiently unlikely under a specified model. It is a different task from calibrating a classifier against catalog labels.",
            "Neither a low CNN score nor a high one gives the September 23 unmatched teaching case a defensible planet probability. That snapshot did not quantify it with validated, applicable evidence."
          ]
        },
        {
          "title": "Read calibration labels beside the metric",
          "paragraphs": [
            "Temperature scaling divides logits by a positive fitted temperature before sigmoid. It changes confidence, while preserving ranking and the binary 0.5 boundary. Our nonlinear stack carries a frozen temperature of about 0.83621 into the fresh audit; comparator Brier scores use raw logits. Brier is a mean squared confidence error, so different calibration treatment matters. Do not call its smaller Brier proof of an intrinsically better architecture or a planet-confirmation probability."
          ]
        }
      ],
      "example": {
        "title": "Strong evidence can meet a low prior",
        "steps": [
          "Prior planet probability = 1%, so prior odds = 1/99.",
          "A diagnostic is ten times more likely under the planet hypothesis than its single stated alternative.",
          "Posterior odds = 10/99; posterior probability = 10/109 ≈ 9.17%."
        ],
        "answer": "This two-hypothesis teaching calculation is not a real candidate validation: actual alternatives and likelihoods still need justification."
      },
      "project": "Fresh nonlinear Brier is 0.106743 using its frozen temperature; static v4 Brier is 0.135148 from raw logits. These are not matched-calibration comparisons or blind planet probabilities. The authoritative watcher score remains not_calibrated_for_blind_search.",
      "sources": [
        "cal",
        "raven"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "For logit z=0, what is sigmoid(z)?",
          "answer": 0.5,
          "tolerance": 1e-05,
          "unit": "score",
          "explanation": "1/(1+exp(0)) = 1/2.",
          "id": "probability-q1",
          "lesson": "probability"
        },
        {
          "type": "number",
          "prompt": "Prior odds are 1:9 and the likelihood ratio is 3. What is posterior planet probability in percent?",
          "answer": 25,
          "tolerance": 0.01,
          "unit": "%",
          "explanation": "Posterior odds = 3:9 = 1:3; probability = 1/(1+3) = 25%.",
          "id": "probability-q2",
          "lesson": "probability"
        },
        {
          "type": "single",
          "prompt": "A positive temperature rescales binary logits. What happens to ranking?",
          "options": [
            "It stays unchanged.",
            "It reverses every pair.",
            "It becomes perfectly correct.",
            "Every score becomes zero."
          ],
          "answer": 0,
          "explanation": "Division by a positive constant and sigmoid are monotonic operations.",
          "id": "probability-q3",
          "lesson": "probability"
        },
        {
          "type": "multi",
          "prompt": "Which evidence is needed before interpreting a blind-search score as a probability?",
          "options": [
            "Applicable calibration evaluation",
            "A defined positive label and target population",
            "Assessment of shift and selection effects",
            "Only that the output lies between zero and one"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Numerical range alone says nothing about empirical probability validity.",
          "id": "probability-q4",
          "lesson": "probability"
        },
        {
          "type": "single",
          "prompt": "Ten seeds give almost the same high score. What can you conclude?",
          "options": [
            "The fitted models agree under this procedure; shared bias may remain.",
            "The planet probability is exactly that score.",
            "All astrophysical alternatives are ruled out.",
            "No calibration is needed."
          ],
          "answer": 0,
          "explanation": "Agreement can coexist with common training bias or missing diagnostic inputs.",
          "id": "probability-q5",
          "lesson": "probability"
        },
        {
          "type": "single",
          "prompt": "What is the probability of the 23 September unmatched case based solely on its CNN score?",
          "options": [
            "Not established by that score",
            "Exactly 1.458%",
            "Exactly 98.542%",
            "Exactly the DANN ensemble mean"
          ],
          "answer": 0,
          "explanation": "No applicable probability calibration or complete astrophysical validation has been established.",
          "id": "probability-q6",
          "lesson": "probability"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "A ranking score, a calibrated frequency and a scenario-based planet probability answer different questions. Each needs its own evidence and assumptions.",
      "pitfall": "Multiplying an uncalibrated CNN score by 100 only changes its display. It does not turn it into a supported percentage chance of a planet.",
      "prerequisite": "splits"
    },
    {
      "id": "neurons",
      "unit": "learning",
      "order": 13,
      "title": "Inside one prediction",
      "hook": "A neural network is a parameterized numerical function. Start by calculating one neuron yourself.",
      "minutes": 35,
      "objectives": [
        "Calculate a weighted sum and a sigmoid.",
        "Distinguish parameters, features and hyperparameters.",
        "Follow the forward pass through a network."
      ],
      "sections": [
        {
          "title": "A neuron is a small calculation",
          "paragraphs": [
            "Start with two measured inputs, x₁ and x₂. A neuron multiplies each by a weight, adds the results, and adds a bias: z = w₁x₁ + w₂x₂ + b. The weights w₁ and w₂ control each input’s contribution; the bias b shifts the result even when the inputs are zero. In this project, an input might be a flux bin or a transit duration. Training adjusts the weights and bias. It does not turn the measured inputs into weights. Keeping these two roles separate makes the next lesson easier: learning changes the calculation applied to data.",
            "A model architecture specifies which calculations connect to which. A hyperparameter, such as layer width or learning rate, is chosen by the experimenter or a tuning procedure. The training process usually updates weights and biases while keeping these architectural choices fixed."
          ]
        },
        {
          "title": "Nonlinearity makes combinations expressive",
          "paragraphs": [
            "An activation function transforms z. ReLU returns max(0,z); a sigmoid returns 1/(1+exp(−z)). Without nonlinear activations, stacking affine layers still gives one affine mapping, regardless of depth. Nonlinearity lets the network represent interactions and regions with different responses. A hidden representation is an intermediate vector of learned features; it need not correspond to a clean human concept.",
            "The final binary output often uses a sigmoid to produce a score between zero and one. A logit is the value before that sigmoid. The sigmoid supplies a convenient scale, not automatic astrophysical probability calibration."
          ]
        },
        {
          "title": "The forward pass does not learn by itself",
          "paragraphs": [
            "During a forward pass, inputs flow through the current weights to produce predictions. Inference means using a fitted model to predict. Learning requires an additional objective and an update step. Merely sending new watcher data through a frozen CNN does not train it.",
            "Feature scaling affects the magnitudes presented to a model. If one scalar is measured in thousands and another in fractions, their gradients can behave very differently. Apply the frozen training normalizer in the same feature order during inference; never recompute it separately for each candidate."
          ]
        }
      ],
      "example": {
        "title": "Predict by hand",
        "steps": [
          "Let x=[2, −1], w=[0.5, 1] and b=0.2.",
          "z = 0.5×2 + 1×(−1) + 0.2 = 0.2.",
          "sigmoid(0.2) ≈ 0.5498."
        ],
        "answer": "This is one current prediction. No weight changed during the calculation."
      },
      "project": "The research website runs inference with saved checkpoints. New products can create new scored candidates without changing any CNN or DANN weights.",
      "sources": [
        "torch"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "For x=3, w=2 and b=−1, calculate z=wx+b.",
          "answer": 5,
          "tolerance": 0.0001,
          "unit": "logit",
          "explanation": "2×3 − 1 = 5.",
          "id": "neurons-q1",
          "lesson": "neurons"
        },
        {
          "type": "number",
          "prompt": "What is ReLU(−4)?",
          "answer": 0,
          "tolerance": 0,
          "unit": "activation",
          "explanation": "ReLU(z)=max(0,z), so negative inputs map to zero.",
          "id": "neurons-q2",
          "lesson": "neurons"
        },
        {
          "type": "multi",
          "prompt": "Which are ordinarily learned parameters?",
          "options": [
            "A layer’s weights",
            "A layer’s biases",
            "The chosen learning-rate setting",
            "The name of the training file"
          ],
          "answer": [
            0,
            1
          ],
          "explanation": "Weights and biases are optimized. The learning rate is a hyperparameter, and a filename is metadata.",
          "id": "neurons-q3",
          "lesson": "neurons"
        },
        {
          "type": "single",
          "prompt": "What happens when several affine layers are stacked with no nonlinear activation?",
          "options": [
            "They can be represented by one affine transformation.",
            "They automatically become a Transformer.",
            "They can represent every nonlinear function exactly.",
            "They no longer have parameters."
          ],
          "answer": 0,
          "explanation": "Composition of affine mappings remains affine; nonlinear activation supplies additional expressiveness.",
          "id": "neurons-q4",
          "lesson": "neurons"
        },
        {
          "type": "single",
          "prompt": "A frozen model scores a new light curve. Has it learned from that curve?",
          "options": [
            "No, unless an explicit training update is performed.",
            "Yes, every forward pass updates weights.",
            "Only if the score exceeds 0.5.",
            "Yes, if the file is new."
          ],
          "answer": 0,
          "explanation": "Inference evaluates a function with fixed parameters; training changes the function.",
          "id": "neurons-q5",
          "lesson": "neurons"
        },
        {
          "type": "single",
          "prompt": "Why preserve feature order in the normalizer and network input?",
          "options": [
            "Each learned weight and scale corresponds to a specific input meaning.",
            "Feature order is always irrelevant.",
            "The sigmoid sorts features automatically.",
            "It controls the catalog’s spelling."
          ],
          "answer": 0,
          "explanation": "Swapping duration and depth can produce a valid-shaped but scientifically invalid prediction.",
          "id": "neurons-q6",
          "lesson": "neurons"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Inputs carry measurements; weights and biases determine the calculation; training adjusts those parameters. Inference uses the parameters already learned.",
      "pitfall": "A forward pass alone does not learn. The watcher can score new light curves without changing its frozen CNN.",
      "prerequisite": "probability"
    },
    {
      "id": "gradients",
      "unit": "learning",
      "order": 14,
      "title": "Loss, backpropagation and one real update",
      "hook": "Learning is repeated error correction. Follow the exact arithmetic from a wrong answer to a changed weight.",
      "minutes": 35,
      "objectives": [
        "Explain supervised labels and a loss function.",
        "Calculate a derivative and gradient update.",
        "Connect the chain rule to backpropagation."
      ],
      "sections": [
        {
          "title": "The loss gives a direction, not understanding",
          "paragraphs": [
            "After making a prediction, the model needs a numerical way to judge its error. In supervised learning, each training example pairs an input x with a target y. The prediction is written ŷ, pronounced “y-hat.” A loss turns the prediction error into a number to minimize. For our first calculation, use L = ½(ŷ − y)²: subtract the target, square the difference, then halve it. Larger errors cost more, regardless of their sign. For binary labels y∈{0,1}, a common loss is cross-entropy: −[y ln(s) + (1−y)ln(1−s)], where s is the predicted score. It penalizes confident wrong predictions strongly.",
            "Labels define what is learned. If negatives accidentally include uninvestigated planets, or labels correlate with processing artifacts, reducing the loss can teach the wrong rule. Optimization faithfully follows the supplied task; it cannot repair missing scientific truth on its own."
          ]
        },
        {
          "title": "A derivative tells you the local slope",
          "paragraphs": [
            "To improve one weight, ask how the loss would change if you nudged that weight a little. A derivative measures this local slope. For prediction ŷ = wx and loss L = ½(wx − y)², the derivative is ∂L/∂w = (wx − y)x. The symbol ∂ means a partial derivative: change this parameter while holding the others fixed. The error (wx − y) tells you whether the prediction is high or low; multiplying by x accounts for how strongly w changes the prediction.",
            "Gradient descent uses w ← w − η∂L/∂w. Read the arrow as “replace the old weight with.” The learning rate η controls the step size. A negative gradient makes the update increase w; a positive gradient makes it decrease w. Either direction is meant to reduce the loss locally. A step that is too large can overshoot, so the sign alone is not a guarantee of improvement.",
            "A network has many weights, so it needs many such derivatives: together they form the gradient. Backpropagation computes them efficiently with the chain rule, tracing how a change flows through successive calculations to the loss. It multiplies local derivatives along each path and adds contributions where paths meet. The gradients are recalculated at the current weights on the next training step."
          ]
        },
        {
          "title": "Separate the three phases",
          "paragraphs": [
            "Follow one training step in order. First, the forward pass produces predictions using the current weights. Next, the loss compares those predictions with the targets. Then backward() computes how each trainable parameter contributed to that loss. Finally, optimizer.step() changes the parameters using those gradients and the optimizer’s update rule. Computing a gradient is not itself a weight update.",
            "PyTorch usually adds new gradients to existing ones. Call zero_grad() before the next independent gradient calculation unless you deliberately want to accumulate several batches. For inference, model.eval() changes the behavior of layers such as dropout. Disabling gradient recording, for example with no_grad(), serves a different purpose: it avoids recording calculations for differentiation and saves memory.",
            "Repeat these steps over many batches and the training loss may fall. The next question is whether the learned rule works on unseen examples. That ability is generalization. We measure it separately because a model can fit its training data by learning shortcuts that do not hold for new stars."
          ]
        }
      ],
      "example": {
        "title": "Update a one-weight model",
        "steps": [
          "Take x=2, target y=4, weight w=1 and learning rate η=0.1.",
          "Prediction wx=2; loss ½(2−4)²=2. Gradient (2−4)×2=−4.",
          "Update w=1−0.1×(−4)=1.4. New prediction is 2.8 and new loss is 0.72."
        ],
        "answer": "The weight increased because the prediction was too small for positive x. The first loss fell from 2 to 0.72."
      },
      "project": "Each pilot fit uses 120 optimizer updates. This is a training budget, not proof of convergence. The saved checkpoints record the result of those numerical updates.",
      "sources": [
        "torch"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "For ŷ=wx, x=2, y=4 and w=1, compute ∂L/∂w for L=½(ŷ−y)².",
          "answer": -4,
          "tolerance": 0.0001,
          "unit": "gradient",
          "explanation": "(wx−y)x = (2−4)×2 = −4.",
          "id": "gradients-q1",
          "lesson": "gradients"
        },
        {
          "type": "number",
          "prompt": "Starting at w=1 with gradient −4 and learning rate 0.1, what is the next weight?",
          "answer": 1.4,
          "tolerance": 0.0001,
          "unit": "weight",
          "explanation": "wnew = 1 − 0.1×(−4) = 1.4.",
          "id": "gradients-q2",
          "lesson": "gradients"
        },
        {
          "type": "single",
          "prompt": "What is backpropagation calculating?",
          "options": [
            "Gradients of the loss with respect to parameters using the chain rule",
            "The prediction errors copied backward unchanged through every layer",
            "New weights chosen independently to minimize each layer’s local error",
            "The best architecture found by trying every connection pattern"
          ],
          "answer": 0,
          "explanation": "Backprop efficiently propagates derivative information through the computation graph.",
          "id": "gradients-q3",
          "lesson": "gradients"
        },
        {
          "type": "single",
          "prompt": "Why normally call zero_grad() between independent training updates in PyTorch?",
          "options": [
            "Gradients otherwise accumulate.",
            "It restores the original weights before every batch.",
            "It removes the need for optimizer.step().",
            "It turns evaluation-mode dropout back on."
          ],
          "answer": 0,
          "explanation": "Clearing gradients is distinct from resetting parameters.",
          "id": "gradients-q4",
          "lesson": "gradients"
        },
        {
          "type": "multi",
          "prompt": "Which belong in a standard supervised training iteration?",
          "options": [
            "Forward prediction",
            "Loss and gradient calculation",
            "Parameter update",
            "Automatic validation of a newly discovered planet"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The numerical loop trains a label predictor; scientific validation is outside that loop.",
          "id": "gradients-q5",
          "lesson": "gradients"
        },
        {
          "type": "single",
          "prompt": "Training loss falls steadily. What does that establish?",
          "options": [
            "The model is fitting the supplied training objective better.",
            "It must generalize to TESS.",
            "It has no label errors.",
            "It cannot overfit."
          ],
          "answer": 0,
          "explanation": "Training fit and held-out performance must be assessed separately.",
          "id": "gradients-q6",
          "lesson": "gradients"
        }
      ],
      "lab": "gradient",
      "code": "# Runnable pure-Python training loop: one weight, one example.\nx, target, weight, rate = 2.0, 4.0, 1.0, 0.1\nfor step in range(5):\n    prediction = weight * x\n    loss = 0.5 * (prediction - target) ** 2\n    gradient = (prediction - target) * x\n    print(step, round(weight, 4), round(loss, 4))\n    weight -= rate * gradient",
      "takeaway": "A gradient tells you how sensitive the loss is to each parameter. Backpropagation computes it; the optimizer uses it to update the weights.",
      "pitfall": "With a negative gradient, subtracting it increases the weight. Work through both minus signs before guessing the update direction.",
      "prerequisite": "neurons"
    },
    {
      "id": "training",
      "unit": "learning",
      "order": 15,
      "title": "Batches, optimizers and overfitting",
      "hook": "The model can improve its training score while becoming worse at the actual scientific task.",
      "minutes": 35,
      "objectives": [
        "Distinguish steps, batches and epochs.",
        "Interpret train/validation learning curves.",
        "Explain regularization, early stopping and compute budgets."
      ],
      "sections": [
        {
          "title": "How the dataset reaches the optimizer",
          "paragraphs": [
            "A model usually learns from a small batch of examples at a time. It predicts for the batch, computes a loss and uses the resulting gradient to update its weights. One such optimizer update is a training step. An epoch normally means one pass through the dataset, but check how the sampler works: sampling with replacement can show the same example several times and skip others. Our pilot allows 120 steps with batches of 32. That is 120 × 32 = 3,840 example draws per fit. It does not mean 3,840 different stars, or that each star was used equally often.",
            "Stochastic gradient descent uses batch gradients. Momentum smooths the update direction using previous updates. Adam keeps running estimates of gradient moments to adapt updates per parameter. None guarantees the best generalization. Learning-rate schedules change step size over time; compare optimizers with a documented tuning and compute budget."
          ]
        },
        {
          "title": "Read both curves",
          "paragraphs": [
            "Training loss asks how well the model fits examples used to update it. Validation loss asks how it behaves on reserved examples. If training improves while validation worsens persistently, overfitting is a plausible explanation. If both remain poor, investigate input mistakes, capacity, optimization and labels. A single noisy validation point is not a trend.",
            "Early stopping selects a checkpoint using a prespecified validation rule. It is model selection and must not use the final audit. If the best checkpoint is the last allowed update, you have not shown that training converged; the budget may simply have ended."
          ]
        },
        {
          "title": "Control complexity and shortcuts",
          "paragraphs": [
            "Weight decay discourages large weights under its optimizer-specific implementation. Dropout randomly removes activations during training, discouraging dependence on particular pathways; evaluation generally uses the full network with the corresponding scaling convention. Data augmentation creates label-preserving variations, but an astronomical transformation must preserve the intended physical label. Distorting a dip until it disappears is not automatically valid augmentation.",
            "A GPU accelerates parallel tensor calculations; it does not make a split valid or a model calibrated. Small models and datasets can be practical on CPUs. Report steps, batch sizes, data exposure, tuning costs and hardware so apparent performance gains can be interpreted fairly."
          ]
        }
      ],
      "example": {
        "title": "Count the actual work",
        "steps": [
          "A dataset contains 320 examples. Batch size is 32 with no dropped final batch.",
          "One sequential epoch takes 10 updates.",
          "Five epochs use 50 updates and 1,600 example presentations."
        ],
        "answer": "Presentations count compute exposure; there are still only 320 distinct original examples."
      },
      "project": "The five-arm pilot equalizes a short 120-update budget per seed. Several best checkpoints occur at the limit, so the negative DANN result is informative for this pilot but not proof that every DANN configuration fails.",
      "sources": [
        "torch"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "A dataset has 320 examples and batch size 32, without replacement or dropping rows. How many steps are in one epoch?",
          "answer": 10,
          "tolerance": 0,
          "unit": "steps",
          "explanation": "320/32 = 10.",
          "id": "training-q1",
          "lesson": "training"
        },
        {
          "type": "number",
          "prompt": "120 updates each use 32 examples. How many example draws occur?",
          "answer": 3840,
          "tolerance": 0,
          "unit": "draws",
          "explanation": "120×32 = 3840 draws; repeats may occur.",
          "id": "training-q2",
          "lesson": "training"
        },
        {
          "type": "single",
          "prompt": "Training loss falls while validation loss persistently rises. What is a plausible diagnosis?",
          "options": [
            "Overfitting",
            "Guaranteed convergence to the best scientific model",
            "Perfect calibration",
            "A larger independent test set"
          ],
          "answer": 0,
          "explanation": "The model is improving training fit while losing held-out performance.",
          "id": "training-q3",
          "lesson": "training"
        },
        {
          "type": "multi",
          "prompt": "Which are legitimate controls when used and evaluated appropriately?",
          "options": [
            "Early stopping on tuning data",
            "Weight decay",
            "Physically justified augmentation",
            "Selecting checkpoints by final audit performance"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The first three can regularize or select a model. Audit-driven checkpoint selection compromises evaluation.",
          "id": "training-q4",
          "lesson": "training"
        },
        {
          "type": "single",
          "prompt": "What can you infer if the best validation checkpoint is the last allowed update?",
          "options": [
            "The run may need more training; convergence is unestablished.",
            "All weights have reached their exact optimum.",
            "The model is invalid by definition.",
            "Another seed cannot change anything."
          ],
          "answer": 0,
          "explanation": "A budget boundary is not a convergence certificate.",
          "id": "training-q5",
          "lesson": "training"
        },
        {
          "type": "single",
          "prompt": "What does a GPU primarily change?",
          "options": [
            "The speed and execution of supported numerical computations",
            "The meaning of a positive label",
            "The independence of the audit set",
            "Whether a score is a planet probability"
          ],
          "answer": 0,
          "explanation": "Hardware affects compute behavior, not the scientific definition of the task.",
          "id": "training-q6",
          "lesson": "training"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "A step counts an update; a batch supplies examples for that update; an epoch depends on the sampling rule. Track validation behavior as well as training loss.",
      "pitfall": "Reaching the allowed final step means the budget ended. It does not show that the model converged or that more training would help.",
      "prerequisite": "gradients"
    },
    {
      "id": "seeds",
      "unit": "learning",
      "order": 16,
      "title": "What a random seed actually does",
      "hook": "Seed 42 is not a model setting that makes planets easier to find. It starts a reproducible stream of pseudo-random choices.",
      "minutes": 35,
      "objectives": [
        "Explain pseudo-random generators and repeatable streams.",
        "Identify random components of training.",
        "Interpret seed spread and reproducibility limits."
      ],
      "sections": [
        {
          "title": "A seed initializes a state machine",
          "paragraphs": [
            "A computer often produces “random” numbers using a repeatable recipe. This is a pseudo-random number generator: its internal state determines the next number and how the state changes afterward. A seed chooses the starting state. If you use the same generator, seed and sequence of calls, you get the same number sequence. Think of the seed as a starting point for a repeatable experiment, not a setting that makes the model smarter. The number 42 is not scientifically special. Different seeds give different starting sequences, which can lead training along different paths.",
            "Random numbers can initialize weights, shuffle training rows, sample batches, choose dropout masks and create augmentations. In a controlled experiment, these choices influence the optimization path. Two runs can learn different weights and slightly different rankings even with the same architecture and data."
          ]
        },
        {
          "title": "One number does not control every source of variation",
          "paragraphs": [
            "Setting a seed is useful, but ask which random generator you actually set. Python’s random module, NumPy and PyTorch can each maintain their own state. Data-loader workers may also need explicit seeds. If an extra random draw happens before weight initialization, later draws move to different positions in the sequence even though the initial seed is unchanged. Reproducibility depends on the sequence of operations as well as the starting number.",
            "There is another source of variation: numerical execution. Different devices, software versions, parallel reduction orders or nondeterministic operations can produce different results without changing the intended random choices. Record the environment and use deterministic operations when exact replay matters.",
            "Separate retraining from replaying predictions. Retraining asks the optimizer to recreate weights and may require many controls. Replaying a saved checkpoint starts from already fitted weights. Verify the checkpoint bytes, preprocessing, feature order, code and inference mode; you do not need to train again just to view its saved result."
          ]
        },
        {
          "title": "Use seeds to measure training variability",
          "paragraphs": [
            "Report results across prespecified seeds and include each run, rather than selecting the luckiest. Seed standard deviation measures variability from those training runs; it is not the same as uncertainty over all possible stars, labels or future surveys. Bootstrap uncertainty on a fixed cohort addresses a different source of variation.",
            "A model ensemble combines predictions from several fitted models, often by averaging. It can reduce some variance but still share the same dataset bias and blind spots. Three agreeing seeds do not establish calibrated confidence or represent every uncertainty. Fixing data splits while changing model seeds helps isolate training variation; changing both mixes effects."
          ]
        }
      ],
      "example": {
        "title": "Three honest runs",
        "steps": [
          "Suppose prespecified seeds produce AP values 0.70, 0.72 and 0.68.",
          "The mean AP is 0.70; sample standard deviation is 0.02.",
          "Reporting only 0.72 would hide the run-to-run variability and introduce selection bias."
        ],
        "answer": "Keep seed-level results and distinguish training variability from cohort-sampling uncertainty."
      },
      "project": "Our pilot uses seeds 42, 43 and 44 for each of five approaches, yielding 15 fits. It retains all checkpoints and per-seed candidate scores. The original report’s bootstrap seed is 2718; that resampling seed is separate from model-training seeds.",
      "sources": [
        "torch",
        "numpy"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What is the most accurate description of a seed?",
          "options": [
            "An initial state for a pseudo-random number generator",
            "A fixed initial weight assigned identically to every neuron",
            "The random fraction of examples reserved for testing",
            "The number of optimizer updates before convergence"
          ],
          "answer": 0,
          "explanation": "A seed controls a repeatable number stream under the same generator and call sequence.",
          "id": "seeds-q1",
          "lesson": "seeds"
        },
        {
          "type": "multi",
          "prompt": "Which operations commonly use random numbers during training?",
          "options": [
            "Weight initialization",
            "Batch shuffling",
            "Dropout masks",
            "The fixed definition of transit depth"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Training choices can be stochastic; the physical definition does not depend on a seed.",
          "id": "seeds-q2",
          "lesson": "seeds"
        },
        {
          "type": "number",
          "prompt": "Three seeds give AP 0.70, 0.72 and 0.68. What is their mean AP?",
          "answer": 0.7,
          "tolerance": 0.0001,
          "unit": "AP",
          "explanation": "(0.70+0.72+0.68)/3 = 0.70.",
          "id": "seeds-q3",
          "lesson": "seeds"
        },
        {
          "type": "single",
          "prompt": "Why can the same seed produce different results after a code change?",
          "options": [
            "The order of random draws or numerical operations may have changed.",
            "A fixed seed guarantees identical weights across any changed architecture.",
            "Only the dataset size can affect reproducibility once a seed is set.",
            "A seed controls the final accuracy directly, regardless of the update path."
          ],
          "answer": 0,
          "explanation": "Reproducibility depends on the computation and environment, not just one integer.",
          "id": "seeds-q4",
          "lesson": "seeds"
        },
        {
          "type": "single",
          "prompt": "What does standard deviation across three training seeds measure most directly?",
          "options": [
            "Variation among those fitted runs under the stated setup",
            "All astrophysical uncertainty",
            "The probability that a candidate is a planet",
            "The exact future-survey error rate"
          ],
          "answer": 0,
          "explanation": "Seed spread does not substitute for independent-cohort evaluation or physical validation.",
          "id": "seeds-q5",
          "lesson": "seeds"
        },
        {
          "type": "single",
          "prompt": "You ran ten seeds and report only the best. What is the issue?",
          "options": [
            "The reported result is selected and optimistic.",
            "The model now has ten times more independent test stars.",
            "The seed becomes calibrated.",
            "There is no issue if the architecture is fixed."
          ],
          "answer": 0,
          "explanation": "Selecting favorable runs creates another model-selection step that must be disclosed.",
          "id": "seeds-q6",
          "lesson": "seeds"
        }
      ],
      "lab": "seed",
      "code": "import random\na = random.Random(42)\nb = random.Random(42)\nleft = [a.random() for _ in range(3)]\nright = [b.random() for _ in range(3)]\nassert left == right\nprint(left)  # Same generator, seed and call sequence.\n# This does not seed NumPy, PyTorch or every hardware operation.",
      "takeaway": "A seed starts a repeatable pseudo-random sequence. Prespecified seeds help you measure how much the training result depends on random choices.",
      "pitfall": "The same seed does not guarantee identical results across changed code, devices or libraries. The best seed is not an unbiased summary.",
      "prerequisite": "training"
    },
    {
      "id": "cnn",
      "unit": "architectures",
      "order": 17,
      "title": "CNNs: learn a detector that slides",
      "hook": "A convolutional filter can respond to a dip wherever it appears. Calculate the response before stacking layers.",
      "minutes": 35,
      "objectives": [
        "Compute a small one-dimensional convolution-like response.",
        "Explain channels, receptive fields and pooling.",
        "Understand global/local light-curve branches."
      ],
      "sections": [
        {
          "title": "One filter, repeated across positions",
          "paragraphs": [
            "Imagine moving a small ruler with three adjustable numbers along a light curve. At each position, multiply the three local flux values by those numbers and add the products. You have applied one filter. A one-dimensional CNN repeats the same weights across positions, so it can respond to a learned pattern wherever that pattern appears in the input. This reuse is called weight sharing. During training, backpropagation adjusts the filter values to help reduce the loss. Most ML libraries use the stored filter order for this calculation, technically cross-correlation; you do not need to reverse it for the worked example.",
            "A kernel width of three sees three adjacent input bins at one layer. Multiple output channels learn different responses. Padding controls edge treatment; stride controls how far the window moves. With no padding and stride one, an input of length N and kernel width k produces N−k+1 positions."
          ]
        },
        {
          "title": "Build context without pretending it is physics",
          "paragraphs": [
            "The receptive field is the input region that can influence a representation. Stacking convolutions, using wider or dilated kernels and downsampling can enlarge it. Pooling summarizes nearby activations, often by a maximum or average, and reduces resolution. This can improve tolerance to small shifts but lose timing or morphology detail.",
            "A CNN’s learned filters may detect edges, dips or dataset artifacts. A plausible activation plot does not prove causal reasoning. Test controlled changes, known failure cases and out-of-domain examples. The same architecture can learn astronomy or shortcuts depending on labels and data preparation."
          ]
        },
        {
          "title": "Why global and local views coexist",
          "paragraphs": [
            "A global phase-folded view contains the whole orbit and may expose secondary events or broad variability. A local view zooms into the proposed transit and preserves ingress/egress detail. Scalar features supply quantities such as period and duration. Separate branches can encode each input before their representations are combined for a final score.",
            "Folding assumes an ephemeris. If blind search gives the wrong period, the network sees a distorted representation. Global/local CNNs are established methods, not a unique invention of this repository."
          ]
        },
        {
          "title": "One architecture, two different jobs",
          "paragraphs": [
            "A candidate CNN reads a folded global view and a close-up local view, looking for repeated morphology. An event localizer scans observations for where something happened. Both can use convolution, but the inputs, outputs and labels differ. Our deployed candidate scorer is the frozen Kepler CNN; the v2/v3 event localizers and their pixel branches belong to separate research experiments. An injection-recovery gain cannot be substituted for a candidate-classification score."
          ]
        }
      ],
      "example": {
        "title": "Slide a simple curvature filter",
        "steps": [
          "Use a three-point window [1.0, 0.9, 1.0] and filter [1, −2, 1].",
          "Response = 1×1.0 − 2×0.9 + 1×1.0 = 0.2.",
          "On a flat [1.0, 1.0, 1.0] window, the response is zero."
        ],
        "answer": "This hand-chosen teaching filter reacts to a local depression. A real CNN learns many filters and is not restricted to this one."
      },
      "project": "Our shared input has global and local three-channel views plus seven scalars. Both the reference classifier and the adaptation experiment depend on keeping this contract consistent.",
      "sources": [
        "astro"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "Compute the response of filter [1,−2,1] on window [1,0.9,1].",
          "answer": 0.2,
          "tolerance": 0.0001,
          "unit": "response",
          "explanation": "1 − 1.8 + 1 = 0.2.",
          "id": "cnn-q1",
          "lesson": "cnn"
        },
        {
          "type": "number",
          "prompt": "Input length 10, kernel width 3, stride 1, no padding: how many output positions?",
          "answer": 8,
          "tolerance": 0,
          "unit": "positions",
          "explanation": "N−k+1 = 10−3+1 = 8.",
          "id": "cnn-q2",
          "lesson": "cnn"
        },
        {
          "type": "single",
          "prompt": "What does weight sharing mean in a CNN?",
          "options": [
            "The same filter is applied at multiple positions.",
            "Every output channel uses the same filter values.",
            "The local and global branches must have identical parameters.",
            "All training seeds use the same initialized network."
          ],
          "answer": 0,
          "explanation": "Shared local filters reduce parameters and recognize similar patterns at different locations.",
          "id": "cnn-q3",
          "lesson": "cnn"
        },
        {
          "type": "multi",
          "prompt": "What can a global phase view add to a local transit view?",
          "options": [
            "Possible secondary events elsewhere in phase",
            "Broad orbital-phase variability",
            "Context beyond ingress and egress",
            "A direct spectroscopic planet mass"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Global context contains more of the orbit, but photometry does not directly supply a spectroscopic mass.",
          "id": "cnn-q4",
          "lesson": "cnn"
        },
        {
          "type": "single",
          "prompt": "What is a possible cost of pooling?",
          "options": [
            "Loss of fine timing or shape information",
            "Creation of extra measured transits",
            "Guaranteed physical interpretability",
            "Removal of every bias"
          ],
          "answer": 0,
          "explanation": "Summarizing nearby values trades resolution for a coarser representation.",
          "id": "cnn-q5",
          "lesson": "cnn"
        },
        {
          "type": "single",
          "prompt": "How are most CNN filters obtained?",
          "options": [
            "Optimized from data through gradients",
            "Manually assigned a planet name",
            "Copied from the evaluation labels at inference",
            "Drawn anew for every prediction after training"
          ],
          "answer": 0,
          "explanation": "Filters are parameters learned during training, then fixed for ordinary inference.",
          "id": "cnn-q6",
          "lesson": "cnn"
        }
      ],
      "lab": "convolution",
      "code": "import torch\nfrom torch import nn\ntorch.set_num_threads(2)\ntorch.manual_seed(42)  # Controls this PyTorch generator, not every library.\n# Synthetic residual sequences: 16 examples, 1 channel, 20 bins.\nx = 0.02 * torch.randn(16, 1, 20)\ny = torch.cat([torch.zeros(8), torch.ones(8)])\nx[8:, :, 8:12] -= 0.2  # Positive class: an artificial dip, not a planet label.\nmodel = nn.Sequential(nn.Conv1d(1, 4, 3), nn.ReLU(),\n                      nn.AdaptiveAvgPool1d(1), nn.Flatten(), nn.Linear(4, 1))\noptimizer = torch.optim.Adam(model.parameters(), lr=0.01)\nfor step in range(30):\n    optimizer.zero_grad()\n    logits = model(x).squeeze(1)\n    loss = nn.functional.binary_cross_entropy_with_logits(logits, y)\n    loss.backward()\n    optimizer.step()\nprint('Final training loss:', round(loss.item(), 4))\n# This teaches the training loop. It has no independent validation set;\n# its training loss is not evidence of exoplanet-detection performance.",
      "takeaway": "A convolution reuses a small learned filter across positions. Multiple layers combine local responses into broader patterns useful for the training task.",
      "pitfall": "The illustrative filter is hand chosen so you can calculate it. A trained CNN learns its filter values and may also learn unwanted shortcuts.",
      "prerequisite": "seeds"
    },
    {
      "id": "alternatives",
      "unit": "architectures",
      "order": 18,
      "title": "Useful baselines: linear models, trees and sequences",
      "hook": "A simpler model is often the fastest way to discover whether the expensive one is solving the right problem.",
      "minutes": 35,
      "objectives": [
        "Explain logistic regression and boosted trees.",
        "Compare recurrent models with convolutions.",
        "Choose baselines suited to available evidence."
      ],
      "sections": [
        {
          "title": "Start with a transparent benchmark",
          "paragraphs": [
            "Before building a larger network, ask how well a simpler model can use the same evidence. Logistic regression takes a weighted sum of input features and applies a sigmoid. It is linear in log-odds unless you add interaction terms or nonlinear features yourself. With useful inputs such as transit duration and diagnostic measurements, it can provide a strong baseline. A baseline is a reference you must improve on under a fair comparison. If a simple model works just as well, that tells you something useful about the task and the information available.",
            "A decision tree partitions feature space through tests such as duration < threshold. Random forests average many diversified trees. Gradient boosting adds weak models sequentially to improve an objective, commonly using shallow trees. These methods handle tabular diagnostic features well; they do not automatically model raw time-series relationships without an appropriate representation."
          ]
        },
        {
          "title": "Models that carry a state through time",
          "paragraphs": [
            "A recurrent neural network updates a hidden state as it reads a sequence. LSTMs and GRUs add gates that regulate what information is retained or forgotten, helping with long dependencies compared with a basic recurrent cell. Sequential computation can make very long sequences costly to train.",
            "A temporal convolution uses local filters and can process positions in parallel; dilation expands context. Attention lets positions interact through content-dependent weights. None is universally best. Irregular timestamps, missing observations and observing gaps must be represented explicitly, regardless of architecture."
          ]
        },
        {
          "title": "Match the comparison to the scientific input",
          "paragraphs": [
            "A tabular model given centroid diagnostics is not a pure architecture comparison against a CNN given only flux. You changed the information as well as the model. Separate representation gains from architecture gains with ablations. Compare a constant-prevalence predictor, simple scalar model, established CNN and the proposed model on identical grouped partitions.",
            "Measure label efficiency, runtime, calibration and failure categories as well as ranking. If a simpler model reaches comparable performance with fewer labels and easier auditing, it may be the better operational choice. Popularity is not an evaluation metric."
          ]
        }
      ],
      "example": {
        "title": "A misleading model contest",
        "steps": [
          "Model A is a CNN with folded flux only.",
          "Model B is a boosted tree with flux statistics, difference-image offsets and secondary-eclipse diagnostics.",
          "B wins on the same audit."
        ],
        "answer": "B is a better tested system, but the result alone cannot attribute the gain to trees rather than the extra diagnostic inputs."
      },
      "project": "The historical five-arm pilot compared training approaches within a shared neural input setup. Later studies add a Transformer, diagnostic experts and static/nonlinear stacks. Keep simple task-matched baselines and input ablations when testing another architecture.",
      "sources": [
        "raven",
        "triage"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What does standard logistic regression model linearly?",
          "options": [
            "Log-odds as a function of its input features",
            "The exact orbital trajectory",
            "Every possible nonlinear relation without feature design",
            "The raw probability without a link function"
          ],
          "answer": 0,
          "explanation": "The sigmoid of a linear score yields a linear relation in log-odds.",
          "id": "alternatives-q1",
          "lesson": "alternatives"
        },
        {
          "type": "single",
          "prompt": "What distinguishes gradient boosting from one decision tree?",
          "options": [
            "It builds a sequence of models to improve an objective.",
            "It never uses labels.",
            "It is a type of period folding.",
            "It guarantees calibrated planet probabilities."
          ],
          "answer": 0,
          "explanation": "Boosting combines successive weak learners rather than relying on one tree.",
          "id": "alternatives-q2",
          "lesson": "alternatives"
        },
        {
          "type": "multi",
          "prompt": "Which are useful reasons to include a simple baseline?",
          "options": [
            "Detecting whether extra complexity adds value",
            "Measuring compute and label efficiency",
            "Making some failure patterns easier to inspect",
            "Guaranteeing the complex model will lose"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "A baseline supplies evidence for or against complexity; its outcome is not predetermined.",
          "id": "alternatives-q3",
          "lesson": "alternatives"
        },
        {
          "type": "single",
          "prompt": "Why can a CNN-versus-tree comparison with different inputs be hard to interpret?",
          "options": [
            "Input information and architecture are confounded.",
            "Trees cannot process numbers.",
            "CNNs have no parameters.",
            "The audit labels must be different."
          ],
          "answer": 0,
          "explanation": "A win could come from extra diagnostics rather than the model family.",
          "id": "alternatives-q4",
          "lesson": "alternatives"
        },
        {
          "type": "single",
          "prompt": "What do LSTM/GRU gates primarily control?",
          "options": [
            "Information flow through a recurrent hidden state",
            "Whether a star physically transits",
            "The telescope aperture",
            "Catalog publication permissions"
          ],
          "answer": 0,
          "explanation": "Gated recurrent models regulate memory and updates along a sequence.",
          "id": "alternatives-q5",
          "lesson": "alternatives"
        },
        {
          "type": "single",
          "prompt": "Which model handles missing astronomical data automatically without any design choice?",
          "options": [
            "None of these architectures guarantees that.",
            "Every Transformer",
            "Every CNN",
            "Every logistic regression"
          ],
          "answer": 0,
          "explanation": "Missingness, masks and time intervals must be represented and evaluated explicitly.",
          "id": "alternatives-q6",
          "lesson": "alternatives"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Choose a model based on its inputs and the question you want to answer. A simple, well-tested baseline makes improvements easier to interpret.",
      "pitfall": "If one model receives extra diagnostic evidence, its advantage is not automatically an architecture advantage. Test those factors separately.",
      "prerequisite": "cnn"
    },
    {
      "id": "attention",
      "unit": "architectures",
      "order": 19,
      "title": "Transformers: learn which observations to compare",
      "hook": "Attention builds a weighted mixture of information. It does not magically know which timestamps belong together.",
      "minutes": 35,
      "objectives": [
        "Compute simple normalized attention weights.",
        "Explain queries, keys, values and positions.",
        "Compare direct time-series search with folded classification."
      ],
      "sections": [
        {
          "title": "From samples to tokens",
          "paragraphs": [
            "A Transformer starts by representing each input unit as a vector called a token. For a light curve, a token could describe a small patch of samples. Attention lets one token combine information from others. Each token produces three learned vectors: a query for making comparisons, a key to compare against, and a value containing information to combine. The query–key dot products determine compatibility scores. Scaled dot-product attention is softmax(QKᵀ/√dₖ)V. Read it from left to right: compare queries and keys, scale by the square root of key dimension dₖ, turn scores into weights, then take a weighted combination of the values.",
            "Softmax exponentiates each score and normalizes by their sum, making weights positive and summing to one. The output is a weighted combination of value vectors. These weights concern internal information routing, not the probability that a planet exists."
          ]
        },
        {
          "title": "Time has to be represented",
          "paragraphs": [
            "Attention without positional information does not inherently know the chronological order of tokens. Positional or time encodings provide ordering and separation information. Astronomical observations can be irregular, so actual time gaps may matter more than a simple row index. Padding masks prevent missing positions from being treated as ordinary data.",
            "Multiple heads learn different projections and comparison patterns. Residual connections, normalization and feed-forward layers support deeper transformations. Dense self-attention compares pairs of tokens and typically has quadratic cost in sequence length; patching, sparse attention and other sequence models address this at the cost of design tradeoffs."
          ]
        },
        {
          "title": "Architecture does not define the task",
          "paragraphs": [
            "A Transformer can classify an already folded candidate or search an unfolded light curve. These are different tasks with different labels and evaluation. Direct search can inspect single events without requiring a period beforehand, but must demonstrate event localization and false-alarm control. Folded classification gains a prepared periodic representation but inherits ephemeris errors.",
            "Salinas et al. (2025) demonstrate a TESS FFI search with unfolded flux plus background and centroid series. Their candidate output should not be read as a list of automatically confirmed planets. Use their paper to study the task boundary, not to claim attention universally beats CNNs."
          ]
        },
        {
          "title": "The implemented Transformer expert",
          "paragraphs": [
            "In our classifier comparison, attention supplies one sequence-based expert alongside five CNN/DANN regimes. Convolution shares local filters; attention lets a representation combine information from other positions, with time/position encoding needed to interpret the order. Neither mechanism guarantees superiority. The experts must receive documented inputs and be tested on the same hosts. Our implemented candidate Transformer is not the unfolded-light-curve search described by an external paper, and neither is the live watcher scorer."
          ]
        }
      ],
      "example": {
        "title": "Two-token attention",
        "steps": [
          "Suppose attention scores are ln(3) and ln(1)=0.",
          "Exponentiation gives 3 and 1; normalized weights are 0.75 and 0.25.",
          "If the corresponding scalar values are 2 and 10, the output is 0.75×2 + 0.25×10 = 4."
        ],
        "answer": "The output mixes values using learned compatibility. It is not an astrophysical posterior."
      },
      "project": "A Transformer candidate expert has been implemented and evaluated alongside CNNs. It is one of eleven comparison experts, not the watcher scorer. A direct-search Transformer over unfolded observations would require its own search and evaluation contract.",
      "sources": [
        "attention",
        "transformer"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "Attention weights are 0.75 and 0.25; scalar values are 2 and 10. What is the weighted output?",
          "answer": 4,
          "tolerance": 0.0001,
          "unit": "output",
          "explanation": "0.75×2 + 0.25×10 = 1.5 + 2.5 = 4.",
          "id": "attention-q1",
          "lesson": "attention"
        },
        {
          "type": "number",
          "prompt": "Softmax receives two equal finite scores. What weight does each receive?",
          "answer": 0.5,
          "tolerance": 0.0001,
          "unit": "weight",
          "explanation": "Equal exponentiated scores share the total equally.",
          "id": "attention-q2",
          "lesson": "attention"
        },
        {
          "type": "multi",
          "prompt": "What information is often essential for light-curve attention?",
          "options": [
            "Observation times or positional encoding",
            "Masks for unavailable positions",
            "A meaningful token representation",
            "An assumption that token weights are planet probabilities"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Sequence order, missingness and representation define what attention can learn; its weights are not planet probabilities.",
          "id": "attention-q3",
          "lesson": "attention"
        },
        {
          "type": "single",
          "prompt": "Doubling token count under dense pairwise attention roughly changes the number of token pairs by what factor?",
          "options": [
            "Four",
            "Two",
            "One half",
            "No change"
          ],
          "answer": 0,
          "explanation": "Pair count scales approximately as N², so (2N)² = 4N².",
          "id": "attention-q4",
          "lesson": "attention"
        },
        {
          "type": "single",
          "prompt": "Why can a direct-search model handle a single transit without an input period?",
          "options": [
            "It can locate an event in the unfolded series.",
            "It already knows the planet’s orbit exactly.",
            "Every single event is a planet.",
            "It removes the need for negative examples."
          ],
          "answer": 0,
          "explanation": "Event detection can precede period inference, though validation and alias constraints remain.",
          "id": "attention-q5",
          "lesson": "attention"
        },
        {
          "type": "single",
          "prompt": "A bright attention map highlights a dip. What does this establish by itself?",
          "options": [
            "An internal routing pattern, requiring further diagnostic tests",
            "Proof that removing that highlighted input must change the prediction most",
            "A calibrated probability assigned to the highlighted transit",
            "A causal explanation that rules out other input pathways"
          ],
          "answer": 0,
          "explanation": "Attention visualization is not automatically a faithful causal explanation or scientific validation.",
          "id": "attention-q6",
          "lesson": "attention"
        }
      ],
      "lab": "attention",
      "code": "import torch\n# One scalar query, three scalar keys and values: a teaching calculation.\nquery = torch.tensor([1.0])\nkeys = torch.tensor([-1.0, 0.0, 1.0])\nvalues = torch.tensor([2.0, 4.0, 10.0])\nweights = torch.softmax(query * keys, dim=0)\noutput = (weights * values).sum()\nprint('Weights:', weights.tolist())\nprint('Weighted output:', output.item())\nassert torch.allclose(weights.sum(), torch.tensor(1.0))\n# A full Transformer learns vector projections and includes position/masks,\n# multiple heads, residual connections and feed-forward layers.",
      "takeaway": "Queries and keys determine how strongly tokens interact; values supply the information being combined. Time encodings and masks tell the model about order and missing observations.",
      "pitfall": "Attention weights sum to one across the compared tokens. They are not probabilities that those tokens contain planets.",
      "prerequisite": "alternatives"
    },
    {
      "id": "representation",
      "unit": "architectures",
      "order": 20,
      "title": "Learning from unlabeled light curves",
      "hook": "Modern representation learning asks what can be learned before someone labels each star. The objective still matters.",
      "minutes": 35,
      "objectives": [
        "Compare supervised, self-supervised and semi-supervised learning.",
        "Explain masked reconstruction and contrastive learning.",
        "Identify leakage and augmentation hazards in pretraining."
      ],
      "sections": [
        {
          "title": "Build the label from the data",
          "paragraphs": [
            "You may have many light curves but few trustworthy planet labels. Self-supervised learning uses the data itself to create a training task. For example, hide a patch of a light curve and ask a model to predict the missing values from the surrounding samples. The unhidden original supplies the target, so this task does not need a human planet label. An autoencoder instead compresses an input and learns to reconstruct it. Both can learn useful structure, but predicting flux well is not the same as detecting planets well: a rare, shallow transit might be smoothed away as noise.",
            "Supervised fine-tuning then adapts the representation using task labels. Semi-supervised learning combines labeled and unlabeled examples during task training, for example through consistency constraints or carefully filtered pseudo-labels. Pseudo-labeling means using model predictions as provisional targets, which can amplify existing mistakes."
          ]
        },
        {
          "title": "Contrastive learning needs a physical definition of sameness",
          "paragraphs": [
            "Contrastive objectives pull representations of related views closer while distinguishing other examples or representations. The views must preserve the information relevant to the eventual task. Changing flux scale or shifting an ephemeris may be acceptable under a specific representation; deleting the only transit can destroy the label. Two observations of one star are not necessarily identical in event content.",
            "Pretraining can reduce label needs, but must be tested with a label-efficiency curve: performance as the number of allowed labeled groups varies. Compare equal downstream data and tuning budgets, and account for the pretraining compute and archive access."
          ]
        },
        {
          "title": "Large is not automatically foundational for this task",
          "paragraphs": [
            "A foundation model is typically pretrained broadly and reused across tasks. A large Transformer trained on one small disposition table does not become broadly validated merely by being called foundational. Modern approaches worth investigating include masked sequence learning, contrastive representations, multimodal fusion and efficient long-sequence architectures. This course treats these as research directions, not as implemented capabilities or a ranked leaderboard.",
            "Unlabeled access can still cross an evaluation boundary. If a method sees the final audit light curves during pretraining, disclose that transductive setting and compare accordingly. For a claim about new unseen stars, keep their data outside all fitting stages. Check whether representation learning preserves low-SNR transit information using controlled injections."
          ]
        },
        {
          "title": "Pretraining needs a downstream test",
          "paragraphs": [
            "Research-only AI-telescope pilots have used unlabeled light-curve and pixel windows for pretraining before event localization. That can encourage a useful representation, but the task objective must still test whether small transits survive. The fresh recovery experiment reused v3 weights; it did not fit a new representation. A future residual-prediction study should compare against the same frozen detectors at a fixed control budget, including the weak signals every current method misses."
          ]
        }
      ],
      "example": {
        "title": "A pretraining experiment with a real test",
        "steps": [
          "Pretrain on allowed training-pool light curves using masked patches.",
          "Fine-tune with 50, 100 and 200 labeled star groups; compare with training from scratch.",
          "Evaluate each setup on the same untouched groups and on shallow injected events."
        ],
        "answer": "A useful result is better label efficiency without erasing rare signals, not simply lower reconstruction loss."
      },
      "project": "Research-only AI-telescope work has tested pretraining and event localization; it is separate from the watcher. Residual-prediction or broader foundation-model experiments remain possible next studies, not measured improvements in the fresh recovery run.",
      "sources": [
        "attention",
        "torch"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What makes masked reconstruction self-supervised?",
          "options": [
            "The target is derived from hidden parts of the input itself.",
            "Every target is a confirmed planet label.",
            "It never updates weights.",
            "It guarantees useful transit features."
          ],
          "answer": 0,
          "explanation": "The training signal is constructed from the data; downstream usefulness still needs evaluation.",
          "id": "representation-q1",
          "lesson": "representation"
        },
        {
          "type": "multi",
          "prompt": "Which are risks in light-curve representation learning?",
          "options": [
            "Augmentations erasing transits",
            "Audit-star data leaking into pretraining",
            "Pseudo-labels reinforcing mistakes",
            "Unlabeled data making every split automatically valid"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Self-supervision changes the objective, not the need for physical validity and careful evaluation.",
          "id": "representation-q2",
          "lesson": "representation"
        },
        {
          "type": "single",
          "prompt": "How do you test a claim of improved label efficiency?",
          "options": [
            "Compare held-out performance across fixed labeled-group budgets.",
            "Report only the pretraining loss.",
            "Count model parameters.",
            "Choose one easy candidate."
          ],
          "answer": 0,
          "explanation": "A label-efficiency curve measures the gain for a stated amount of supervision.",
          "id": "representation-q3",
          "lesson": "representation"
        },
        {
          "type": "single",
          "prompt": "A reconstruction model has large error on a new star. What follows?",
          "options": [
            "The input is poorly reconstructed and needs investigation.",
            "It must contain a new planet.",
            "Its radius is known.",
            "The model is calibrated."
          ],
          "answer": 0,
          "explanation": "Anomaly can reflect instrumental, stellar or preprocessing differences as well as transits.",
          "id": "representation-q4",
          "lesson": "representation"
        },
        {
          "type": "single",
          "prompt": "A model pretrained on audit-star light curves is evaluated on those same stars. What must be disclosed?",
          "options": [
            "The audit inputs were available during fitting; this is not fully unseen-star evaluation.",
            "Only the learning rate",
            "Nothing because labels were hidden",
            "Only the plot dimensions"
          ],
          "answer": 0,
          "explanation": "Unlabeled access is still a form of information access and changes the evaluation setting.",
          "id": "representation-q5",
          "lesson": "representation"
        },
        {
          "type": "single",
          "prompt": "Which is a physically questionable positive-view augmentation for transit learning?",
          "options": [
            "Removing the only transit while claiming the view retains its event content",
            "A documented small timing shift that preserves the event",
            "A tested label-preserving noise perturbation",
            "A consistent unit conversion applied to values and errors"
          ],
          "answer": 0,
          "explanation": "Deleting the only event destroys the information the downstream task needs.",
          "id": "representation-q6",
          "lesson": "representation"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Self-supervision learns from targets constructed from the data. Its usefulness for planets must be checked with downstream labels and signal-preservation tests.",
      "pitfall": "A low reconstruction error can coexist with erased shallow transits. Evaluate the scientific objective, not just the pretraining loss.",
      "prerequisite": "attention"
    },
    {
      "id": "transfer",
      "unit": "transfer",
      "order": 21,
      "title": "Transfer learning: what exactly is being transferred?",
      "hook": "You can reuse weights, combine labels or align representations. These are different experiments.",
      "minutes": 35,
      "objectives": [
        "Distinguish source and target domains.",
        "Compare frozen transfer, fine-tuning and pooling.",
        "Recognize negative transfer and domain shift."
      ],
      "sections": [
        {
          "title": "A domain is a data-generating context",
          "paragraphs": [
            "Suppose you train on Kepler and want to use the model on TESS. Kepler is the source domain; TESS is the target domain. A domain includes the observing conditions and the way examples and labels were selected. Changes in the distribution of inputs are called covariate shift. Label shift concerns changing class proportions under specific assumptions. The relationship between inputs and labels can also change. In practice, several changes can happen together: cadence, crowding, noise, baseline and catalog decisions all matter. Before adapting a network, identify which differences could make a Kepler rule unreliable on TESS.",
            "Shared input shapes make software compatible but do not guarantee shared meaning or distribution. For example, the same binned transit can contain different numbers of underlying exposures and different residual systematics."
          ]
        },
        {
          "title": "Four approaches you can distinguish",
          "paragraphs": [
            "Frozen transfer applies an existing source model without changing its weights. Fine-tuning starts from source-trained weights and updates some or all of them using target labels. Pooling trains on a combined source/target dataset, with explicit sampling and label rules. Target-only training uses only target-domain labels and is essential as a baseline: additional source data can hurt.",
            "Feature extraction with a frozen backbone and a newly trained head is another useful transfer variant. Which layers to unfreeze, how much to update and how domains are sampled are experimental choices. Equal row counts do not necessarily mean equal independent information."
          ]
        },
        {
          "title": "A gain is conditional on the budget and population",
          "paragraphs": [
            "Negative transfer occurs when transferred information reduces target performance relative to an appropriate comparator. This may result from mismatched labels, shortcuts, incompatible noise or optimization choices. Do not diagnose the cause from a single aggregate score. Examine learning curves and performance by cadence, signal strength, period and stellar properties.",
            "Compare methods on the same grouped target audit, with prespecified seeds and fair tuning. A cross-mission result on known, correctly folded planets does not establish performance on unknown blind detections. “Zero-shot” means no target-task training under a stated setup; it does not mean no evaluation selection or no prior knowledge anywhere in the pipeline."
          ]
        },
        {
          "title": "Why complementary experts might help",
          "paragraphs": [
            "Transit morphology asks what the dip looks like. Variability measures the wider behavior of the star. TLS compares transit-shaped periodic templates. Aperture photometry asks whether the signal survives a change in extracted pixels; difference images ask where the changing light is located. The Transformer and five CNN/DANN regimes provide other learned summaries. These eleven experts offer different evidence, but physical experts in the labeled studies use known catalog ephemerides: they do not demonstrate blind search.",
            "A static stack combines expert scores with fixed learned weights. The nonlinear stack uses regularized trees to learn joint patterns, then blends with the static v4 prior. Selection chose at most seven leaves per tree, L2 regularization 10 and a 0.5 blend. Extra flexibility needs fresh evaluation because it can also learn development-specific patterns."
          ]
        }
      ],
      "example": {
        "title": "Design a useful transfer comparison",
        "steps": [
          "Train a TESS-only baseline on the allowed TESS labels.",
          "Compare source pretraining plus TESS fine-tuning, and pooled training, under recorded budgets.",
          "Evaluate paired predictions on exactly the same reserved TESS groups."
        ],
        "answer": "This isolates whether source information helps this target task; it does not prove that transfer always helps or always fails."
      },
      "project": "Our completed pilot includes TESS-only, fresh Kepler-only, fine-tuned, pooled and supervised DANN arms. The newly trained short-budget Kepler-only arm is distinct from the older frozen reference CNN used by the watcher.",
      "sources": [
        "dann",
        "exominer"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What is fine-tuning?",
          "options": [
            "Starting from learned weights and updating them on the target task or domain",
            "Applying a frozen checkpoint without updates",
            "Changing only the website theme",
            "A period-search grid refinement in every context"
          ],
          "answer": 0,
          "explanation": "Fine-tuning reuses learned parameters as an initialization for additional training.",
          "id": "transfer-q1",
          "lesson": "transfer"
        },
        {
          "type": "multi",
          "prompt": "Which are essential transfer-learning comparators in this project?",
          "options": [
            "Target-only training",
            "Pooled source/target training",
            "Source pretraining plus target fine-tuning",
            "Only the most complicated adaptation method"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Simple approaches show whether adaptation machinery adds value.",
          "id": "transfer-q2",
          "lesson": "transfer"
        },
        {
          "type": "single",
          "prompt": "What is negative transfer?",
          "options": [
            "Transfer reduces target performance compared with an appropriate baseline.",
            "The sigmoid output is negative.",
            "A transit has negative depth by definition.",
            "The seed is less than zero."
          ],
          "answer": 0,
          "explanation": "Negative transfer describes a harmful performance effect, not a numerical sign convention.",
          "id": "transfer-q3",
          "lesson": "transfer"
        },
        {
          "type": "single",
          "prompt": "Do equal input array shapes establish that Kepler and TESS have the same data distribution?",
          "options": [
            "No; measurement and selection differences remain.",
            "Yes, for any CNN.",
            "Yes, if both arrays contain floats.",
            "Only if both filenames end in .npz."
          ],
          "answer": 0,
          "explanation": "Software compatibility does not remove scientific domain shift.",
          "id": "transfer-q4",
          "lesson": "transfer"
        },
        {
          "type": "single",
          "prompt": "A model is evaluated without TESS fine-tuning on selected confirmed TESS planets. What does this directly test?",
          "options": [
            "Transfer on that selected control cohort",
            "Blind-search completeness for the full TESS observing program",
            "Calibrated alert precision in an unlabeled all-sky search",
            "A demonstration that all target-domain false positives are rejected"
          ],
          "answer": 0,
          "explanation": "The selection and task define the scope of the result.",
          "id": "transfer-q5",
          "lesson": "transfer"
        },
        {
          "type": "single",
          "prompt": "Why compare predictions on the same audit examples?",
          "options": [
            "It reduces cohort differences as a confounder and enables paired comparisons.",
            "It forces all methods to have the same score.",
            "It makes the labels unnecessary.",
            "It calibrates each model automatically."
          ],
          "answer": 0,
          "explanation": "A common cohort supports a controlled comparison.",
          "id": "transfer-q6",
          "lesson": "transfer"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Frozen transfer, fine-tuning and pooling use source information in different ways. Compare them against target-only training on the same reserved target groups.",
      "pitfall": "Making input arrays the same shape does not make Kepler and TESS observations statistically equivalent. Transfer can hurt as well as help.",
      "prerequisite": "representation"
    },
    {
      "id": "dann",
      "unit": "transfer",
      "order": 22,
      "title": "DANN: two objectives pull on one representation",
      "hook": "The domain classifier tries to recognize the telescope. The feature extractor is trained to make that harder while keeping the task useful.",
      "minutes": 35,
      "objectives": [
        "Identify feature extractor, task head and domain head.",
        "Calculate the sign-reversed feature gradient.",
        "Explain why domain confusion can fail."
      ],
      "sections": [
        {
          "title": "Three components, two predictions",
          "paragraphs": [
            "Start with a CNN that turns a light curve into a feature vector F(x). DANN adds two heads to that shared representation. The task head C(F(x)) learns to predict the scientific label, such as planet versus non-planet. The domain head D(F(x)) learns to identify which mission supplied the input. Here is the unusual part: the domain head is trained to succeed, while the feature extractor receives a reversed domain gradient that encourages it to hide mission clues. At the same time, the task gradient encourages it to preserve information useful for the scientific label. These two pressures act on the same features.",
            "Classic unsupervised domain adaptation can use source labels and unlabeled target inputs. Our implementation is supervised adaptation with both Kepler and TESS task labels. DANN is a training objective added to a representation, not a replacement for a CNN or Transformer backbone in every sense."
          ]
        },
        {
          "title": "The gradient reversal is the key mechanism",
          "paragraphs": [
            "Focus on one parameter θ in the feature extractor. The task loss supplies a gradient gtask that would help the scientific prediction. The domain loss supplies a gradient gdomain that would help identify the mission. DANN reverses and scales the second contribution, so the feature extractor receives gtask − λgdomain. Here λ is a nonnegative strength setting. The optimizer then applies θ ← θ − η(gtask − λgdomain), with learning rate η. Notice the two different minus signs: one reverses the domain contribution; the outer one is ordinary gradient descent.",
            "The domain head itself does not receive this reversal for its own parameter updates. It still learns to identify the mission by minimizing domain loss. The competition arises because the feature extractor is encouraged to make that task harder while the task head still needs useful class information.",
            "During the forward pass, the gradient-reversal layer returns its input unchanged. Its effect appears only during backpropagation. With λ = 0, the adversarial contribution to feature learning disappears. Some schedules increase λ gradually, letting useful task features form before applying stronger pressure to hide mission differences."
          ]
        },
        {
          "title": "Confusing a domain head is not the scientific goal",
          "paragraphs": [
            "If the domain head is weak, poorly optimized or evaluated on imbalanced domains, its low accuracy says little about invariance. Even with a capable balanced probe, making domains indistinguishable can remove useful task information. Aligning marginal feature distributions can mix classes when label distributions differ. A collapsed representation can confuse the domain head while destroying planet discrimination.",
            "Evaluate target-task performance first, then inspect an independently trained domain probe, class-conditional behavior, λ ablations and learning curves. DANN is an established approach. Its relevance to this project is a testable transfer hypothesis, not architectural novelty or a guarantee of better candidates."
          ]
        },
        {
          "title": "Keep the negative result when the project grows",
          "paragraphs": [
            "The September 23 three-seed pilot still tells us that supervised DANN did not beat pooling or fine-tuning at 120 updates per fit. Later eleven-expert comparisons address a different combination of evidence. Adding the DANN prediction as one expert is not proof that its domain-alignment objective helped, and a new stack does not replace the deployed CNN without a separate deployment decision."
          ]
        }
      ],
      "example": {
        "title": "Reverse only the domain contribution",
        "steps": [
          "Suppose gtask=2, gdomain=3 and λ=0.5.",
          "Feature gradient = 2 − 0.5×3 = 0.5.",
          "At θ=1 and η=0.1, θnew = 1 − 0.1×0.5 = 0.95."
        ],
        "answer": "The domain head still learns to classify the mission. Only its contribution flowing into the shared features is reversed."
      },
      "project": "The completed DANN arm reached mean audit AP 0.6934 versus pooled 0.7067 and fine-tuned 0.7644. It did not earn replacement of the primary watcher CNN. Its scores are available as separate comparison evidence.",
      "sources": [
        "dann"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "For gtask=2, gdomain=3 and λ=0.5, calculate the feature gradient gtask−λgdomain.",
          "answer": 0.5,
          "tolerance": 0.0001,
          "unit": "gradient",
          "explanation": "2 − 0.5×3 = 0.5.",
          "id": "dann-q1",
          "lesson": "dann"
        },
        {
          "type": "number",
          "prompt": "At θ=1, feature gradient 0.5 and learning rate 0.1, what is θ after the update?",
          "answer": 0.95,
          "tolerance": 0.0001,
          "unit": "parameter",
          "explanation": "1 − 0.1×0.5 = 0.95.",
          "id": "dann-q2",
          "lesson": "dann"
        },
        {
          "type": "single",
          "prompt": "What does the domain head itself try to do?",
          "options": [
            "Predict the domain accurately by minimizing its classification loss",
            "Maximize its own classification loss so its predictions become random",
            "Minimize the task head’s planet loss instead of a domain loss",
            "Change the mission labels whenever features become distinguishable"
          ],
          "answer": 0,
          "explanation": "The adversarial conflict comes from reversing its gradient to the feature extractor, not from teaching the domain head to fail.",
          "id": "dann-q3",
          "lesson": "dann"
        },
        {
          "type": "multi",
          "prompt": "Why might 50% domain-head accuracy be unconvincing?",
          "options": [
            "The head may be undertrained",
            "Features may have collapsed",
            "The evaluation may not use balanced, independent domains",
            "It necessarily proves perfect transfer"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Task performance and stronger independent probes are needed to interpret apparent confusion.",
          "id": "dann-q4",
          "lesson": "dann"
        },
        {
          "type": "single",
          "prompt": "What does the gradient reversal layer do during the forward pass?",
          "options": [
            "Passes its input through unchanged",
            "Removes all TESS examples",
            "Reverses the chronological light curve",
            "Randomizes all labels"
          ],
          "answer": 0,
          "explanation": "The identity forward pass preserves the representation; the special action occurs in backpropagation.",
          "id": "dann-q5",
          "lesson": "dann"
        },
        {
          "type": "single",
          "prompt": "What happens to adversarial feature learning when λ=0?",
          "options": [
            "The domain-gradient contribution to the extractor is removed.",
            "The task loss becomes zero automatically.",
            "All examples become Kepler data.",
            "The network gains perfect calibration."
          ],
          "answer": 0,
          "explanation": "With λ=0 the feature gradient contains only the task contribution under the stated formula.",
          "id": "dann-q6",
          "lesson": "dann"
        }
      ],
      "lab": "dann",
      "code": "import torch\nclass Reverse(torch.autograd.Function):\n    @staticmethod\n    def forward(ctx, features, strength):\n        ctx.strength = strength\n        return features.view_as(features)  # Identity in the forward pass.\n    @staticmethod\n    def backward(ctx, incoming_gradient):\n        return -ctx.strength * incoming_gradient, None\n\nfeatures = torch.tensor([1.0], requires_grad=True)\nreversed_features = Reverse.apply(features, 0.5)\ndomain_loss_example = 3 * reversed_features.sum()\ndomain_loss_example.backward()\nprint(features.grad.item())  # -1.5: incoming gradient 3, reversed × 0.5.\nassert features.grad.item() == -1.5\n# This isolates the reversal mechanism. A real DANN additionally has a\n# task loss and a domain head whose own parameters minimize domain loss.",
      "takeaway": "DANN asks shared features to support the task while hiding mission information from a domain classifier. The task result on reserved TESS examples decides whether this helps.",
      "pitfall": "A confused domain head is not enough: the representation may have lost useful class information, or the domain head may simply be weak.",
      "prerequisite": "transfer"
    },
    {
      "id": "uncertainty",
      "unit": "transfer",
      "order": 23,
      "title": "Ensembles, OOD and knowing when to abstain",
      "hook": "A sensible pipeline can say “needs a human” instead of forcing every unfamiliar signal into a confident label.",
      "minutes": 35,
      "objectives": [
        "Distinguish sources of uncertainty.",
        "Interpret ensemble disagreement and OOD scores.",
        "Explain selective prediction and conformal coverage limits."
      ],
      "sections": [
        {
          "title": "Two useful uncertainty questions",
          "paragraphs": [
            "Consider two difficult cases. In the first, a transit is so shallow that measurement noise hides its shape. In the second, a clear instrumental pattern is unlike anything the model saw during training. These suggest different kinds of uncertainty. Ambiguity associated with the measurements and their variability is often called aleatoric uncertainty. Uncertainty from limited training data or model knowledge is often called epistemic uncertainty. The distinction is useful, but depends on the model and assumptions. A single CNN score does not neatly separate the two, and collecting better measurements may help a different problem from collecting more training labels."
          ]
        },
        {
          "title": "Agreement and anomaly are diagnostics",
          "paragraphs": [
            "A deep ensemble trains multiple models and combines their predictions. Disagreement can flag instability, but all members may share the same shortcut. Monte Carlo dropout samples predictions with dropout enabled under a specified approximation; it is not interchangeable with fully independent training. An OOD, or out-of-distribution, detector tries to recognize inputs unlike an allowed reference population.",
            "Distances in representation space, density estimates, reconstruction errors and output-based scores provide different signals. A high anomaly score is not a planet score. It may identify corrupted input, a new cadence, a stellar flare or a rare transit. Evaluate OOD methods on realistic shifts and report what the reference distribution was."
          ]
        },
        {
          "title": "Abstention creates a measurable operating policy",
          "paragraphs": [
            "Selective prediction lets the system defer uncertain cases. Coverage is the fraction of cases it accepts for automatic handling; selective risk is error on those accepted cases. Plot the tradeoff and track human workload. Choosing a reject threshold requires held-out evaluation, and rejected cases still matter scientifically.",
            "Conformal prediction constructs prediction sets or intervals using calibration residuals or nonconformity scores. Under assumptions such as exchangeability, it can provide marginal coverage across future examples. This does not promise the same coverage for every individual star or shifted subgroup, and it does not create a planet posterior. A set containing both planet and non-planet expresses unresolved classification under that procedure."
          ]
        },
        {
          "title": "A router must earn its complexity",
          "paragraphs": [
            "A router changes expert weights according to a case’s diagnostics. It is attractive when experts fail on different kinds of stars, but estimating who is reliable is itself a learning problem. Behavioral v4 and diagnostic v5 did not beat their strongest declared comparators. With host-disjoint cross-fitted competence learning, selection chose routing strength zero: the static prior. That is a useful rejection of adaptation under this evidence, not a successful adaptive system."
          ]
        }
      ],
      "example": {
        "title": "Agreement can hide a shared mistake",
        "steps": [
          "Three models trained on the same mislabeled data score a spacecraft artifact 0.91, 0.92 and 0.91.",
          "The spread is small, but the models share the same training error.",
          "A quality-flag or pixel diagnostic may reveal what the ensemble missed."
        ],
        "answer": "Low spread means agreement under the modeling procedure, not that all relevant uncertainty is small."
      },
      "project": "The reused-audit nonlinear advantage did not repeat as a ranking advantage over static v4 on the fresh 14. Three positive labels make the estimate fragile. The saved fresh AP bootstrap compares nonlinear with variability, not with static v4; seed ranges do not quantify planet probability.",
      "sources": [
        "cal",
        "conformal"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What does a large OOD score most directly indicate?",
          "options": [
            "Unusualness relative to a stated reference distribution",
            "A high planet probability",
            "A confirmed catalog mismatch",
            "A precisely measured radius"
          ],
          "answer": 0,
          "explanation": "Unusual inputs need interpretation; anomaly does not identify a physical cause.",
          "id": "uncertainty-q1",
          "lesson": "uncertainty"
        },
        {
          "type": "multi",
          "prompt": "Which can make ensemble members confidently wrong together?",
          "options": [
            "Shared label errors",
            "Shared preprocessing shortcuts",
            "Shared missing diagnostic information",
            "Independent timestamps correctly recorded"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Common biases remain common even when model seeds differ.",
          "id": "uncertainty-q2",
          "lesson": "uncertainty"
        },
        {
          "type": "number",
          "prompt": "A selective classifier automatically handles 800 of 1,000 cases. What is its coverage in percent?",
          "answer": 80,
          "tolerance": 0.01,
          "unit": "%",
          "explanation": "800/1000 = 80%.",
          "id": "uncertainty-q3",
          "lesson": "uncertainty"
        },
        {
          "type": "single",
          "prompt": "A conformal method has a marginal 95% coverage guarantee under exchangeability. Does that imply a 95% planet probability for one candidate?",
          "options": [
            "No; coverage and an individual class posterior are different quantities.",
            "Yes, by definition.",
            "Only if its CNN score is 0.95.",
            "Yes, even under arbitrary domain shift."
          ],
          "answer": 0,
          "explanation": "Coverage concerns the procedure’s set or interval behavior under assumptions, not individual posterior probability.",
          "id": "uncertainty-q4",
          "lesson": "uncertainty"
        },
        {
          "type": "single",
          "prompt": "What should accompany a policy that rejects uncertain cases?",
          "options": [
            "Accepted-case error, coverage and review workload",
            "Only the best accepted score",
            "A claim that rejected cases do not exist",
            "A guaranteed planet label for every accepted case"
          ],
          "answer": 0,
          "explanation": "Selective policies trade automatic coverage against errors and human effort.",
          "id": "uncertainty-q5",
          "lesson": "uncertainty"
        },
        {
          "type": "single",
          "prompt": "Why inspect retained low-score detections?",
          "options": [
            "The classifier may miss unfamiliar real signals or expose systematic failures.",
            "Every low score must be a new planet.",
            "Low scores are always more reliable.",
            "Their labels are automatically negative."
          ],
          "answer": 0,
          "explanation": "Retaining them supports auditing model misses and selection bias.",
          "id": "uncertainty-q6",
          "lesson": "uncertainty"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Use disagreement and unfamiliarity as reasons to investigate. If the system defers cases, evaluate both the errors it avoids and the workload it creates.",
      "pitfall": "Several models can agree because they share a bias. A narrow score range does not measure every source of uncertainty.",
      "prerequisite": "dann"
    },
    {
      "id": "frontier",
      "unit": "transfer",
      "order": 24,
      "title": "What researchers are doing now",
      "hook": "Read recent systems by their task, inputs and evidence. A collection of incomparable headline scores is not a leaderboard.",
      "minutes": 35,
      "objectives": [
        "Compare classification, direct search and validation systems.",
        "Identify the contribution of recent papers.",
        "Separate preprint claims from independently established results."
      ],
      "sections": [
        {
          "title": "Established directions: richer evidence and direct search",
          "paragraphs": [
            "Read recent models by asking where they act in the research workflow and what evidence they receive. ExoMiner++ (2025) combines Kepler/TESS training with several diagnostic views to classify TESS transit signals. For our project, this motivates studying difference images and spacecraft context as well as network architecture. Astronet-Triage-v2 (2023) answers a broader screening question: which signals look like transits or eclipses? Its positive class therefore includes more than planets. Before comparing headline scores, check what each paper counts as a positive and which information is available to its model.",
            "Salinas et al. (2025) use Transformer-based processing of unfolded TESS light curves with background and centroid series. This places the model earlier in the detection chain. Comparing its candidate-search performance with our catalog-folded AP would mix tasks. These are examples of current approaches, not an exhaustive ranking."
          ]
        },
        {
          "title": "From ranking to explicit validation",
          "paragraphs": [
            "RAVEN (2025) combines learned classifiers, simulated false-positive scenarios and priors in a Bayesian framework. The 2026 RAVEN survey manuscript, accepted to MNRAS in the inspected record, reports an automated TESS-SPOC FFI search and newly validated planets within its selection and validation criteria. This demonstrates that a website plus automated search and vetting is not, by itself, a new research concept.",
            "Our inference from these systems: prioritize missing evidence, honest evaluation and a specific failure mode before claiming that a larger architecture is the needed advance. Reproducing another paper’s scope and assumptions is part of a comparison, not an optional footnote."
          ]
        },
        {
          "title": "2026 reading desk: promising, with boundaries",
          "paragraphs": [
            "EXOVEIL (June 2026 preprint) combines self-supervised stellar prediction, residual matched filtering and a boosted-tree vetter. Its reported transfer recovery on 47 confirmed TESS planets is a selected-control result; it does not measure blind-survey purity. Study the separation between its representation objective and detection evaluation.",
            "Astro-Hunters (August 2026 preprint) studies label provenance using twelve TESS hosts and star-disjoint evaluation. It highlights how circular labels and time-conversion errors can dominate apparent model gains. Treat its small scope explicitly. These summaries were checked again on 28 September 2026 (EXOVEIL v3, Astro-Hunters v1); preprints can change and this course has not independently reproduced their reported results."
          ]
        }
      ],
      "example": {
        "title": "Compare the scientific contracts",
        "steps": [
          "Paper A classifies already detected TCEs using folded flux and images.",
          "Paper B searches raw time series for transit events.",
          "Paper C computes scenario-based validation probabilities for an eligible candidate subset."
        ],
        "answer": "They address different stages. First align task, inputs, labels, population and compute before comparing any metric."
      },
      "project": "The local evidence now includes eleven-expert classification and completed physical/fresh event-recovery studies. Read their cohort-specific project tables before comparing them with papers. Background-source rejection, weak-event sensitivity and larger independent classifier validation remain open.",
      "sources": [
        "triage",
        "exominer",
        "transformer",
        "raven",
        "raven26",
        "exoveil",
        "hunters"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "Which distinction matters when comparing Astronet triage with planet classification?",
          "options": [
            "Triage can count eclipsing binaries as useful positive detections.",
            "Both positive classes are necessarily identical.",
            "Triage never uses light curves.",
            "Planet classification measures only runtime."
          ],
          "answer": 0,
          "explanation": "A transit/eclipse detector and a planet-disposition classifier have different labels and error meanings.",
          "id": "frontier-q1",
          "lesson": "frontier"
        },
        {
          "type": "single",
          "prompt": "What is a major direction represented by ExoMiner++?",
          "options": [
            "Combining diagnostic views and multi-mission training",
            "Removing every diagnostic except a file name",
            "Proving a sigmoid is always calibrated",
            "Replacing all evaluation with a website"
          ],
          "answer": 0,
          "explanation": "The paper emphasizes richer diagnostic information together with Kepler/TESS training.",
          "id": "frontier-q2",
          "lesson": "frontier"
        },
        {
          "type": "multi",
          "prompt": "What should be aligned before comparing headline model scores across papers?",
          "options": [
            "Task and label definition",
            "Evaluation population and split",
            "Available input evidence",
            "Only publication year"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Newer publication date does not make incompatible metrics directly comparable.",
          "id": "frontier-q3",
          "lesson": "frontier"
        },
        {
          "type": "single",
          "prompt": "What does recovering all 47 selected confirmed controls establish?",
          "options": [
            "Recovery on that selected set under the stated procedure",
            "Perfect completeness and purity over all unknown TESS signals",
            "A proof that every new anomaly is a planet",
            "A calibrated probability for our candidate"
          ],
          "answer": 0,
          "explanation": "Known-planet control selection limits what can be generalized.",
          "id": "frontier-q4",
          "lesson": "frontier"
        },
        {
          "type": "single",
          "prompt": "How should the two recent 2026 preprints be used in this course?",
          "options": [
            "As current research to scrutinize and potentially reproduce",
            "As independently reproduced results of our repository",
            "As guarantees of superior performance",
            "As official planet confirmations for our detections"
          ],
          "answer": 0,
          "explanation": "Recent manuscripts are valuable reading, but their claims require critical assessment and replication.",
          "id": "frontier-q5",
          "lesson": "frontier"
        },
        {
          "type": "single",
          "prompt": "Why is an automated watcher website alone insufficient as a novelty claim?",
          "options": [
            "Published systems already combine automated search and vetting.",
            "Software can never contribute to research.",
            "Only a new telescope can produce research.",
            "Every CNN is identical."
          ],
          "answer": 0,
          "explanation": "A contribution needs a specific evidenced advance over prior work, which can include well-evaluated software or methods.",
          "id": "frontier-q6",
          "lesson": "frontier"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Compare recent work by its task, inputs, labels and evaluation population. Richer diagnostics, direct search and explicit validation solve different parts of the workflow.",
      "pitfall": "A paper reporting high performance on selected known planets has not necessarily measured false-alert rates in a blind search.",
      "prerequisite": "uncertainty"
    },
    {
      "id": "vetter",
      "unit": "vetting",
      "order": 25,
      "title": "A vetting workflow you can actually follow",
      "hook": "The right next step after “unmatched” is a sequence of evidence checks, not a bigger confidence number.",
      "minutes": 35,
      "objectives": [
        "Order a practical candidate review.",
        "Check event-level and ephemeris evidence.",
        "Write structured decisions with missing evidence explicit."
      ],
      "sections": [
        {
          "title": "Verify the event before explaining it",
          "paragraphs": [
            "Open a candidate as though you had to explain the evidence to another student. Start with the original light curve, before folding. Locate each proposed transit, check its timestamps and flags, and see how many separate events support the signal. Then compare the original series with the detrended and folded views. A convincing folded shape can be built from one bad measurement or from unrelated events stacked together. Your first task is to establish what was actually observed. Keep unavailable checks visible rather than treating them as passed tests."
          ]
        },
        {
          "title": "Test competing timing and morphology hypotheses",
          "paragraphs": [
            "Compare the proposed period with harmonics, known signals and observing-window aliases. A true odd/even comparison separates successive transit events at a proposed orbital period and compares their fitted depths with uncertainties. Alternating phase bins inside one folded transit are not the same test. Inspect possible secondary events and out-of-transit variability without assuming one diagnostic is decisive.",
            "A physical transit fit estimates parameters such as radius ratio, impact parameter and ephemeris under stellar and noise assumptions. Examine residuals and parameter uncertainty, not only the best-fit overlay. Radius plausibility relies on a credible stellar host and contamination treatment."
          ]
        },
        {
          "title": "Make a review decision that can be audited",
          "paragraphs": [
            "A useful human review distinguishes “likely instrumental,” “likely astrophysical false positive,” “plausible candidate needing checks” and “insufficient evidence.” Include reasons, file provenance and remaining work. Missing centroid data is “not assessed,” not “passed.” The next reviewer should be able to reconstruct why you accepted or rejected each hypothesis.",
            "A vetting helper can gather plots, model rankings and catalog checks. It supports judgment; it does not automatically supply a complete astrophysical false-positive probability. Keep raw evidence accessible when the helper’s output seems contradictory."
          ]
        }
      ],
      "example": {
        "title": "One deep point drives the fold",
        "steps": [
          "A folded dip seems strong, but the original series shows one extreme point near a quality-flagged discontinuity.",
          "Remove or investigate that flagged exposure under a documented policy.",
          "Re-run the detection and compare the remaining events."
        ],
        "answer": "If the signal disappears, record the sensitivity instead of presenting the original fold as robust evidence."
      },
      "project": "The Research site already provides a candidate dossier, model comparisons and human-review storage. It is a vetting aid, not a validated autonomous planet certifier. The snapshot inspected on 23 September had no saved human reviews yet.",
      "sources": [
        "dave",
        "lightkurve"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What should follow an unmatched catalog result first?",
          "options": [
            "Inspect the underlying signal and its data quality.",
            "Declare a planet discovery.",
            "Convert the CNN score directly into probability.",
            "Delete all low-score evidence."
          ],
          "answer": 0,
          "explanation": "Unmatched is a catalog-check outcome, so the signal still needs basic verification.",
          "id": "vetter-q1",
          "lesson": "vetter"
        },
        {
          "type": "multi",
          "prompt": "Which are part of an event-level review?",
          "options": [
            "Individual transit timing and depth",
            "Quality flags and gaps",
            "Sensitivity to reasonable detrending choices",
            "Only the phase-folded thumbnail"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The original event context reveals artifacts and inconsistent cycles that a fold may hide.",
          "id": "vetter-q2",
          "lesson": "vetter"
        },
        {
          "type": "single",
          "prompt": "What does a true odd/even transit test compare?",
          "options": [
            "Depths of alternating whole transit events",
            "Alternating bins inside one transit",
            "Every second catalog identifier",
            "Two random model seeds"
          ],
          "answer": 0,
          "explanation": "The test seeks differences between successive orbital events, as in some eclipsing binaries.",
          "id": "vetter-q3",
          "lesson": "vetter"
        },
        {
          "type": "single",
          "prompt": "A diagnostic is not available. Which review label is appropriate?",
          "options": [
            "Not assessed",
            "Passed",
            "Confirmed planet",
            "Zero false-positive probability"
          ],
          "answer": 0,
          "explanation": "Absence of a diagnostic does not support its successful outcome.",
          "id": "vetter-q4",
          "lesson": "vetter"
        },
        {
          "type": "single",
          "prompt": "Why retain rejected and uncertain cases?",
          "options": [
            "To audit false positives, selection and model failures",
            "Because every rejected case is a planet",
            "To inflate discovery counts",
            "To change catalog labels automatically"
          ],
          "answer": 0,
          "explanation": "Failure cases support scientific evaluation and reproducibility.",
          "id": "vetter-q5",
          "lesson": "vetter"
        },
        {
          "type": "single",
          "prompt": "What can the existing vetting helper establish automatically?",
          "options": [
            "A set of documented diagnostics and rankings within its implemented scope",
            "A full validated planet probability for every signal",
            "A mass and radius without stellar data",
            "Catalog novelty across all literature"
          ],
          "answer": 0,
          "explanation": "The helper’s capabilities have explicit boundaries and leave necessary checks to further work.",
          "id": "vetter-q6",
          "lesson": "vetter"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Begin with individual events, then test timing, morphology and source explanations. Save the evidence and the reasoning behind the review decision.",
      "pitfall": "A missing diagnostic belongs in the unresolved column. It should never silently become a passed check.",
      "prerequisite": "frontier"
    },
    {
      "id": "pixels",
      "unit": "vetting",
      "order": 26,
      "title": "Pixels, centroids and the host-star question",
      "hook": "Before asking how large the planet is, determine which star lost the light.",
      "minutes": 35,
      "objectives": [
        "Explain aperture extraction and difference imaging.",
        "Interpret centroid shifts with uncertainties.",
        "Connect nearby stars and dilution to host identity."
      ],
      "sections": [
        {
          "title": "The aperture is a mixture",
          "paragraphs": [
            "A telescope measures light in pixels, and an aperture selects which pixels to add together. Those pixels can contain light from the target and neighboring stars. The resulting light curve describes their combined contribution; it does not automatically identify which star dimmed. Changing the aperture changes the mixture of target light, neighboring light and noise. That is why comparing sensible apertures can help investigate contamination. Before converting transit depth into a planet radius, you need a defensible host-star identification and an estimate of how much other light diluted the event."
          ]
        },
        {
          "title": "Locate the changing light",
          "paragraphs": [
            "A flux-weighted centroid estimates the center of the recorded light distribution. If one component dims, the centroid can move away from that component, depending on the geometry and other flux sources. Interpret shifts relative to uncertainties and control behavior, not by raw magnitude alone. Spacecraft motion can move many stars together.",
            "A difference image subtracts suitably selected in-event and out-of-event images to reveal the location of missing light. Consistent background treatment, event selection, detector orientation and uncertainty matter. A faint or noisy difference source may remain unlocalized. Record the sign convention of the image subtraction so the plotted source is interpreted correctly."
          ]
        },
        {
          "title": "Catalog context complements pixels",
          "paragraphs": [
            "Nearby-source catalogs such as Gaia help identify potential contaminants and constrain stellar properties. Propagate coordinates to an appropriate epoch when proper motion matters, inspect resolution limits and consider unresolved companions. A catalog’s failure to list a close companion is not proof none exists. High-resolution imaging, ground-based photometry or spectroscopy may constrain scenarios that TESS pixels cannot separate.",
            "Combine spatial and temporal evidence: a neighboring eclipsing source with matching period is more informative than a nearby star alone. The physical planet radius and follow-up plan depend on resolving host identity."
          ]
        }
      ],
      "example": {
        "title": "A shift changes the hypothesis",
        "steps": [
          "The target and a fainter neighbor share the aperture.",
          "Difference imaging localizes missing light near the neighbor during repeated events.",
          "A transit model assuming the target’s stellar radius no longer has a secure host assumption."
        ],
        "answer": "Revisit the neighbor’s properties and eclipsing-binary scenarios before reporting a target-planet radius."
      },
      "project": "The 23 September TIC 150428135 teaching dossier had unresolved source evidence. Later pixel experts and physical detector injections do not by themselves resolve that individual dossier; inspect its current evidence before claiming a new outcome.",
      "sources": [
        "crowd",
        "dave"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What is an aperture?",
          "options": [
            "The pixels or weights used to extract a flux measurement",
            "The planet’s orbital period",
            "A neural-network loss function",
            "The catalog publication date"
          ],
          "answer": 0,
          "explanation": "The extraction region determines which light contributes to the measured series.",
          "id": "pixels-q1",
          "lesson": "pixels"
        },
        {
          "type": "multi",
          "prompt": "Which can affect an observed centroid shift?",
          "options": [
            "Which source dimmed",
            "Spacecraft pointing changes",
            "Noise and contamination",
            "Only the planet’s catalog name"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Centroids mix astrophysical, instrumental and measurement effects.",
          "id": "pixels-q2",
          "lesson": "pixels"
        },
        {
          "type": "single",
          "prompt": "A nearby source exists in Gaia. Does that alone prove it caused the dip?",
          "options": [
            "No; timing and spatial evidence must connect it to the event.",
            "Yes, every neighbor is an eclipsing binary.",
            "Yes, if the CNN score is low.",
            "No nearby source can ever cause a dip."
          ],
          "answer": 0,
          "explanation": "Existence supplies a possible scenario, not proof of causation.",
          "id": "pixels-q3",
          "lesson": "pixels"
        },
        {
          "type": "single",
          "prompt": "Difference imaging is too noisy to localize the event. What should the dossier say?",
          "options": [
            "Host localization remains unresolved.",
            "The target is definitely the source.",
            "The event is definitely instrumental.",
            "The planet radius is exact."
          ],
          "answer": 0,
          "explanation": "An inconclusive measurement should remain inconclusive.",
          "id": "pixels-q4",
          "lesson": "pixels"
        },
        {
          "type": "single",
          "prompt": "Why compare multiple apertures?",
          "options": [
            "To test how contamination and extraction affect the event",
            "To manufacture more independent stars",
            "To guarantee a smaller radius",
            "To replace the time axis"
          ],
          "answer": 0,
          "explanation": "Sensitivity to extraction can help distinguish source and systematic explanations.",
          "id": "pixels-q5",
          "lesson": "pixels"
        },
        {
          "type": "single",
          "prompt": "Why might proper motion matter during a catalog cross-match?",
          "options": [
            "A star’s apparent position changes with epoch.",
            "It changes the definition of a ppm.",
            "It makes a seed nondeterministic.",
            "It removes every blended companion."
          ],
          "answer": 0,
          "explanation": "Coordinates observed at different epochs may need propagation before precise matching.",
          "id": "pixels-q6",
          "lesson": "pixels"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "The folded curve tells you that light changed; pixel evidence helps identify where that light came from. Host identification controls the physical interpretation.",
      "pitfall": "Using the target star’s radius before establishing the host can produce a precise-looking radius for the wrong object.",
      "prerequisite": "vetter"
    },
    {
      "id": "validation",
      "unit": "vetting",
      "order": 27,
      "title": "Validation, confirmation and sharing a candidate",
      "hook": "A catalog entry is a useful scientific record. It is not a shortcut around the evidence needed for a planet claim.",
      "minutes": 35,
      "objectives": [
        "Distinguish detection, vetting, validation and confirmation.",
        "Explain scenario-based false-positive probability.",
        "Choose an appropriate submission path."
      ],
      "sections": [
        {
          "title": "Name the stage accurately",
          "paragraphs": [
            "Follow the evidence through three different stages. Detection means you found a signal worth investigating. A candidate is a possible planetary explanation that still needs checks. Statistical validation evaluates specified false-positive alternatives and can support a planet claim when its assumptions and criteria are met. Confirmation usually adds further evidence, such as an independent measurement, interpreted in context. These words describe the evidence available, not how enthusiastic you are about the signal. A high model score, an unmatched catalog result or a catalog submission alone does not complete this chain.",
            "Radial velocities measure a star’s line-of-sight motion and can constrain a companion’s mass or reveal a stellar binary. Transit timing variations can provide dynamical information in suitable systems. Not every candidate is feasible for either method, and follow-up design depends on brightness, period, expected signal and scientific value."
          ]
        },
        {
          "title": "A false-positive probability needs alternatives",
          "paragraphs": [
            "A scenario-based validation compares a planet interpretation with relevant eclipsing binaries, blended systems and other false positives, using observations and population assumptions. Missing a plausible scenario or misidentifying the host can make a posterior misleading. Training-label calibration alone does not perform this astrophysical comparison.",
            "Validation frameworks have eligibility and data requirements. RAVEN’s initial stated period scope is 0.5–16 days, for example. Our approximately 25.3-day proposal cannot inherit the framework’s published guarantees by copying its threshold. A method’s applicability must be established for the actual case."
          ]
        },
        {
          "title": "Prepare a dossier before approaching a catalog",
          "paragraphs": [
            "Check existing planets, candidates, TCEs, eclipsing-binary lists and relevant literature using coordinates, identifiers and harmonic ephemerides. Include target identifiers, sky position, time system, period and epoch uncertainties, duration, depth, data products, plots, diagnostics and limitations. A supervisor or experienced collaborator can help assess the claim and follow-up.",
            "Check the official current ExoFOP-TESS contribution requirements before submitting. The precise policy was last checked here on 23 September 2026 and was not freshly reverified on 28 September. A submitted candidate is still a candidate; the Research website does not automatically publish or certify it."
          ]
        }
      ],
      "example": {
        "title": "A responsible next step",
        "steps": [
          "A signal survives basic review but lacks reliable source localization.",
          "Prepare the reproducible dossier, catalog cross-checks and a targeted request for spatial or follow-up evidence.",
          "Keep the status as a candidate needing investigation."
        ],
        "answer": "Do not substitute a registration request for the missing validation work."
      },
      "project": "The 23 September retained-proposal snapshot established no validated new planet; its highest real reference-CNN score was a known planet match. Later classifier and injection studies are evaluations, not confirmation of a new planet.",
      "sources": [
        "raven",
        "exofop"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What is required for an astrophysical false-positive probability?",
          "options": [
            "Explicit alternatives, priors and applicable evidence",
            "Only a sigmoid output",
            "Only an unmatched TIC identifier",
            "Only three training seeds"
          ],
          "answer": 0,
          "explanation": "A posterior over causes requires a model of those causes and their evidence.",
          "id": "validation-q1",
          "lesson": "validation"
        },
        {
          "type": "multi",
          "prompt": "Which belong in a candidate dossier?",
          "options": [
            "Ephemeris with units and time reference",
            "Data products and diagnostic evidence",
            "Uncertainties and unresolved alternatives",
            "An unsupported statement that the score is probability"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "A useful dossier makes the signal reproducible and its limitations inspectable.",
          "id": "validation-q2",
          "lesson": "validation"
        },
        {
          "type": "single",
          "prompt": "Can an initial 0.5–16-day validation model automatically validate a 25.3-day signal with the same threshold?",
          "options": [
            "No; applicability outside its stated scope needs validation.",
            "Yes, because all periods are numbers.",
            "Yes, if the website loads.",
            "Only by rounding the period to 16."
          ],
          "answer": 0,
          "explanation": "Extrapolating a validation regime is a new scientific assumption.",
          "id": "validation-q3",
          "lesson": "validation"
        },
        {
          "type": "single",
          "prompt": "What does radial-velocity follow-up measure directly?",
          "options": [
            "The star’s line-of-sight velocity variations",
            "A CNN gradient",
            "The exact transit depth in every band",
            "The number of catalog rows"
          ],
          "answer": 0,
          "explanation": "Stellar velocity variations can constrain companion mass and alternative scenarios.",
          "id": "validation-q4",
          "lesson": "validation"
        },
        {
          "type": "single",
          "prompt": "What is the appropriate description after a candidate is listed in a catalog?",
          "options": [
            "A listed candidate with its stated evidence and status",
            "Automatically a confirmed planet",
            "Automatically a novel discovery independent of literature",
            "An object needing no further observations"
          ],
          "answer": 0,
          "explanation": "Registration records a claim or assessment; it does not automatically complete validation.",
          "id": "validation-q5",
          "lesson": "validation"
        },
        {
          "type": "single",
          "prompt": "Before a Community Candidate upload, what should you do?",
          "options": [
            "Check current ExoFOP permissions and publication requirements.",
            "Assume the Research site has already submitted it.",
            "Upload a score with no ephemeris.",
            "Treat a Git push as an astronomical submission."
          ],
          "answer": 0,
          "explanation": "External catalog workflows have their own current eligibility requirements.",
          "id": "validation-q6",
          "lesson": "validation"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "A responsible candidate report states what was detected, what alternatives were tested and what remains unknown. Submission is a way to share evidence for scrutiny.",
      "pitfall": "Catalog acceptance, statistical validation and observational confirmation are distinct steps. Do not use them as interchangeable labels.",
      "prerequisite": "pixels"
    },
    {
      "id": "case",
      "unit": "vetting",
      "order": 28,
      "title": "Case file: the 25.3244-day unmatched signal",
      "hook": "Use our own candidate to practice choosing the next action without inventing a planet probability.",
      "minutes": 35,
      "objectives": [
        "Separate observed facts from model interpretations.",
        "Rank unresolved checks by scientific value.",
        "Interpret disagreement between the reference and comparison models."
      ],
      "sections": [
        {
          "title": "What the stored result actually says",
          "paragraphs": [
            "Treat this candidate as a case file, not a verdict. The 23 September 2026 saved signal on TIC 150428135 has a proposed period of about 25.3244 days and a reference CNN score of about 0.01458. UNMATCHED means that the supported catalog checks did not find a compatible record in the snapshots they used. It leaves several possibilities open, including a new signal, an alias, an artifact or an existing object missed by the limited match. Start by writing down which observations support the period and which predicted events fall in usable coverage. Those questions determine what the result can tell you.",
            "Two observed dips support multiple cycle-count interpretations. P/2, P and 2P need scrutiny, and a predicted intermediate event falling in a gap cannot be treated as a measured absence. More sectors may distinguish hypotheses, but additional data must be inspected with the same care."
          ]
        },
        {
          "title": "Why a different model score does not settle it",
          "paragraphs": [
            "The 23 September comparison evidence gives a DANN mean raw score near 0.6265, while other short-budget approaches also differ from the frozen reference. These models were trained differently and have not been calibrated for blind proposals. The disagreement is a reason to inspect representation and model failure, not to select the largest number as the true planet probability.",
            "The primary score remains unchanged. The side-by-side table retains provenance and seed ranges so you can study sensitivity to training approach. None of these score values measures the probability that an unmatched signal is a novel planet."
          ]
        },
        {
          "title": "The next evidence has a concrete purpose",
          "paragraphs": [
            "First verify original events and known-signal subtraction or masking. Test alias ephemerides against actual coverage and further sectors. Then obtain or inspect target pixels, centroid/difference images, apertures and neighboring-star information to address host ambiguity. Fit a physical transit model with realistic uncertainties only after the event and host assumptions are credible.",
            "A useful review may conclude that the evidence is insufficient. That is scientific progress: it identifies the observation or diagnostic that could change the decision. A new high score without new discriminating evidence would not resolve the current bottleneck."
          ]
        }
      ],
      "example": {
        "title": "Choose between two tempting actions",
        "steps": [
          "Option A: report the largest available model score as the planet probability.",
          "Option B: inspect event coverage and source localization while preserving all model outputs.",
          "B targets the actual unresolved hypotheses."
        ],
        "answer": "The correct next action follows the missing evidence, not the most exciting number."
      },
      "project": "This case preserves the 23 September 2026 teaching snapshot for TIC 150428135, not a live candidate feed. Open Research for current dossiers. The newer classifier and detector experiments do not establish a changed outcome for this signal.",
      "sources": [],
      "quiz": [
        {
          "type": "single",
          "prompt": "What does “unmatched” establish in this case?",
          "options": [
            "No match was found under the implemented checker’s scope.",
            "No astronomer has ever seen the signal.",
            "The signal is definitely a new planet.",
            "The false-positive probability is zero."
          ],
          "answer": 0,
          "explanation": "Checker coverage and matching rules limit the meaning of a non-match.",
          "id": "case-q1",
          "lesson": "case"
        },
        {
          "type": "single",
          "prompt": "Reference score 0.01458 and DANN mean 0.6265 disagree. Which conclusion is justified?",
          "options": [
            "The models rank this input differently; the planet probability remains unestablished.",
            "The planet probability is the larger value.",
            "Average them to get a valid posterior.",
            "The smaller value proves the event is false."
          ],
          "answer": 0,
          "explanation": "Different uncalibrated rankings cannot be converted into a physical posterior by selecting or averaging them.",
          "id": "case-q2",
          "lesson": "case"
        },
        {
          "type": "multi",
          "prompt": "Which checks directly address gaps in the 23 September case file?",
          "options": [
            "Known-signal masking and aliases",
            "Additional event coverage",
            "Pixel/source localization",
            "Choosing the model with the most impressive name"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "These checks target competing timing and host hypotheses.",
          "id": "case-q3",
          "lesson": "case"
        },
        {
          "type": "single",
          "prompt": "A predicted middle transit falls in a gap. What should be recorded?",
          "options": [
            "No observational test of that event was available.",
            "The transit was observed and absent.",
            "The period is confirmed.",
            "The system has no planets."
          ],
          "answer": 0,
          "explanation": "A gap is lack of evidence, not a negative event measurement.",
          "id": "case-q4",
          "lesson": "case"
        },
        {
          "type": "single",
          "prompt": "Why does a known control target still produce unmatched proposals?",
          "options": [
            "Searches can produce aliases, residuals, artifacts or additional signals beyond checker coverage.",
            "Every proposal on a control target is a new planet.",
            "Known targets cannot have noise.",
            "The model has been automatically retrained."
          ],
          "answer": 0,
          "explanation": "A target identity does not determine the cause or catalog match of every detected signal.",
          "id": "case-q5",
          "lesson": "case"
        },
        {
          "type": "single",
          "prompt": "What is a useful review outcome if evidence remains insufficient?",
          "options": [
            "Document uncertainty and the next discriminating check.",
            "Invent a percentage to complete the form.",
            "Delete the raw files.",
            "Declare novelty because the process is slow."
          ],
          "answer": 0,
          "explanation": "An explicit unresolved status with a concrete evidence plan is scientifically useful.",
          "id": "case-q6",
          "lesson": "case"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "The saved period and scores help organize the investigation. The unresolved event timing and source-location evidence determine what to check next.",
      "pitfall": "Choosing the highest score from several models would select the most optimistic output, not establish this candidate’s planet probability.",
      "prerequisite": "validation"
    },
    {
      "id": "contract",
      "unit": "project",
      "order": 29,
      "title": "The project’s exact input contract",
      "hook": "A model checkpoint is only useful when you know what each number entering it means.",
      "minutes": 35,
      "objectives": [
        "Reconstruct the 907-value shared input.",
        "Identify misleading legacy feature names.",
        "Trace preprocessing and normalization provenance."
      ],
      "sections": [
        {
          "title": "Two views and seven scalars",
          "paragraphs": [
            "Before a neural network can score a candidate, the input must match what it was trained to read. Our shared representation has a 200-bin global view covering the folded orbit, a 100-bin local view around the proposed transit, and seven scalar features. These are three complementary summaries of the same proposed event. The array shapes tell the software where to put values, but the scientific contract also specifies their meaning, order, units and preprocessing. A duration in days can fit perfectly into a field that expects hours and still produce the wrong prediction.",
            "The scalars are depth, symmetry, odd_even, bls_snr, bls_depth, bls_duration and bls_period in their implemented order. Their definitions come from the preprocessing code, not from assumptions about their names."
          ]
        },
        {
          "title": "Names are not scientific definitions",
          "paragraphs": [
            "In this legacy contract, odd_even compares alternating phase bins, not alternating whole transit events. bls_snr stores a BLS power statistic rather than a physical white-noise transit SNR. bls_duration is in hours and bls_period is in days. These details affect both interpretation and inference. Renaming or correcting a feature changes the contract and may require regeneration and retraining.",
            "A seven-number vector with duration accidentally in days can pass a shape check while changing its meaning by a factor of 24. Contract tests should cover units, ordering, finite values and representative examples, not just whether a file loads."
          ]
        },
        {
          "title": "The normalizer travels with the model",
          "paragraphs": [
            "The frozen shared normalizer was fitted on 3,759 Kepler TRAIN rows. Reuse its parameters for the corresponding model inputs; fitting a new scale on an individual candidate or on the target audit changes the model being evaluated. Retain checksums for the normalizer, checkpoint, input file and code.",
            "Catalog-prepared inputs and blind-search inputs can differ despite using the same contract: the latter depend on a detected, potentially incorrect ephemeris. This is a scientifically important transfer boundary. Input compatibility is necessary for inference, but it is not evidence of calibrated performance on blind signals."
          ]
        },
        {
          "title": "Tie every score to exact bytes",
          "paragraphs": [
            "The authoritative checkpoint is the September 15 shared_v1 Kepler CNN, paired with frozen Kepler TRAIN normalization. Its scorer checks 200 global bins, 100 local bins, seven scalars and the 907-feature flat representation with the auxiliary branch disabled. Hashes let us test identity rather than trusting a model nickname.",
            "The project map exposes the checkpoint and normalizer hashes in expandable provenance. Completed model_score records from 26 September confirm that identity as checked on 28 September; they do not prove a new scoring event on the check date. The output is a sigmoid ranking score, explicitly not_calibrated_for_blind_search. The saved source-validation F1 threshold near 0.785 is provenance, not a blind-search gate."
          ]
        }
      ],
      "example": {
        "title": "Catch the unit error",
        "steps": [
          "A transit lasts 3 hours.",
          "The contract’s duration scalar should be 3, not 0.125.",
          "0.125 is the same duration in days, but the trained network expects hours for this feature."
        ],
        "answer": "Preserving units is part of reproducing a model, not just formatting a report."
      },
      "project": "FrozenScorer in scripts/research/scoring.py emits authoritative model_score evidence from frozen_Kepler_shared_v1_CNN_seed42. The latest three completed scores inspected on 28 September were saved on 26 September. Checkpoint and normalizer hashes are in the project map.",
      "sources": [],
      "quiz": [
        {
          "type": "number",
          "prompt": "Compute the flattened size of global 200×3, local 100×3 and seven scalars.",
          "answer": 907,
          "tolerance": 0,
          "unit": "values",
          "explanation": "200×3 + 100×3 + 7 = 907.",
          "id": "contract-q1",
          "lesson": "contract"
        },
        {
          "type": "number",
          "prompt": "A transit duration is 0.125 days. What value belongs in a duration feature measured in hours?",
          "answer": 3,
          "tolerance": 0.0001,
          "unit": "hours",
          "explanation": "0.125×24 = 3 hours.",
          "id": "contract-q2",
          "lesson": "contract"
        },
        {
          "type": "single",
          "prompt": "What does the legacy odd_even feature mean here?",
          "options": [
            "Alternating phase-bin comparison",
            "A complete event-by-event odd/even transit test",
            "The seed parity",
            "The number of telescope sectors"
          ],
          "answer": 0,
          "explanation": "The implemented statistic differs from the standard event-level vetting interpretation.",
          "id": "contract-q3",
          "lesson": "contract"
        },
        {
          "type": "single",
          "prompt": "How was the frozen shared normalizer fitted?",
          "options": [
            "On the allowed Kepler TRAIN rows",
            "On each incoming candidate independently",
            "On the final audit labels",
            "On all current website users"
          ],
          "answer": 0,
          "explanation": "Its training-only provenance is part of the frozen inference contract.",
          "id": "contract-q4",
          "lesson": "contract"
        },
        {
          "type": "multi",
          "prompt": "Which artifacts must agree for reproducible inference?",
          "options": [
            "Checkpoint and architecture",
            "Feature definition and normalizer",
            "Input units, ordering and provenance",
            "Only the score’s display precision"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Reproducing a rounded output is not enough if the underlying representation differs.",
          "id": "contract-q5",
          "lesson": "contract"
        },
        {
          "type": "single",
          "prompt": "Why can catalog-folded and blind inputs behave differently with the same array shape?",
          "options": [
            "Blind inputs depend on an estimated, possibly wrong ephemeris.",
            "Array shape always determines statistical distribution.",
            "Blind inputs contain no numbers.",
            "Catalog inputs cannot have noise."
          ],
          "answer": 0,
          "explanation": "Upstream search errors change the representation seen by the classifier.",
          "id": "contract-q6",
          "lesson": "contract"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "A checkpoint expects a specific representation: shapes, order, units, transformations and the matching normalizer. Preserve these together.",
      "pitfall": "A feature can have the right array shape but the wrong units or meaning. Software compatibility does not establish scientific compatibility.",
      "prerequisite": "case"
    },
    {
      "id": "results",
      "unit": "project",
      "order": 30,
      "title": "Read project comparisons without inventing a winner",
      "hook": "The comparison is complete. Its useful result is that this DANN pilot did not outperform simpler transfer approaches.",
      "minutes": 35,
      "objectives": [
        "Read seed means and variability.",
        "Distinguish the frozen benchmark from the new pilot.",
        "State supported conclusions without overclaiming."
      ],
      "sections": [
        {
          "title": "Historical reference and adaptation cohorts",
          "paragraphs": [
            "Before comparing two numbers, check which examples produced them. This repository contains a frozen Kepler-to-TESS reference benchmark and a separate five-arm mission-adaptation pilot. They answer related questions, but they use different evaluation cohorts and should not be treated as one leaderboard. The adaptation pilot compares its five methods on the same 82 TESS audit rows from 79 groups. That audit was reserved from the previous validation pool; it is not an external, previously untouched discovery survey. Keep the cohort description beside the metric so another reader can tell what comparison is supported.",
            "The completed pilot evaluates 82 labeled TESS audit rows from 79 groups, partitioned from the original validation pool. Its original test set was not evaluated in the pilot. Do not compare AP across these cohorts as if one method beat another on the same held-out targets."
          ]
        },
        {
          "title": "The 23 September five-arm result",
          "paragraphs": [
            "Each pilot arm uses seeds 42, 43 and 44 with a short 120-update budget per fit. Mean audit AP ± seed sample standard deviation: TESS-only 0.7474 ± 0.0131; fresh Kepler-only 0.5588 ± 0.0315; fine-tuned 0.7644 ± 0.0180; pooled 0.7067 ± 0.0124; DANN 0.6934 ± 0.0003. The fresh Kepler-only arm is not the older frozen watcher model.",
            "DANN’s mean is below pooling and fine-tuning here. The paired DANN-minus-pooled bootstrap intervals include zero. Low DANN seed spread does not imply superiority or well-calibrated candidate probabilities; a stable method can consistently underperform."
          ]
        },
        {
          "title": "What completion does and does not establish",
          "paragraphs": [
            "All 15 fits completed with receipts and saved selected checkpoints. Several selected checkpoints lie at the update limit, so convergence is not established. No post-audit hyperparameter search was performed to manufacture a better result. A larger, prespecified experiment may answer a different question, but these pilot outcomes should remain visible.",
            "In the 23 September snapshot, all 15 checkpoints were also applied to 44 saved proposals: 17 real known-object controls and 27 synthetic or transformed controls. This verifies comparison inference and preserves per-seed evidence. It is not an independent discovery benchmark. The original reference scores remain primary, and the comparison service appends additional rankings."
          ]
        },
        {
          "title": "Reused versus fresh classifier evidence",
          "paragraphs": [
            "On the reused 82-row audit (44 positive, 38 negative), nonlinear AP is 0.871627, variability 0.863083 and static v4 0.861315. This is development evidence because earlier experiments consulted that audit. On the frozen fresh 14-candidate audit, static v4 ranks better while nonlinear has higher fixed-threshold accuracy. Read the tables in the project map by cohort; do not average these studies into one winner."
          ]
        },
        {
          "title": "Detector recovery asks a different question",
          "paragraphs": [
            "The 90-host physical benchmark and the later 99-host recovery experiment inject events into archival observations. Candidate AP asks whether labeled candidates rank above negatives; recovery asks whether a search locates the injected events at an acceptable control-alert burden. Both neural settings meet the mean control budget on the fresh cohort, but the calibrated threshold sacrifices five events. No classifier or detector comparison here authorizes a deployment or confirms a new planet."
          ]
        }
      ],
      "example": {
        "title": "Make one legitimate paired statement",
        "steps": [
          "On the same pilot audit, mean DANN AP is 0.6934 and pooled AP is 0.7067.",
          "The mean difference is −0.0133.",
          "The reported paired intervals include zero and the training budget is short."
        ],
        "answer": "Report no demonstrated DANN benefit in this pilot, while preserving the limitations and complete results."
      },
      "project": "Read results/crossfit_supermodel_v2/report.md, results/fresh_classifier_audit_v1/README.md and results/ai_telescope_recovery_v1/README.md alongside the historical adaptation pilot. The project map includes served tables with denominators, dates and provenance; no comparison model has replaced the frozen watcher scorer.",
      "sources": [],
      "quiz": [
        {
          "type": "number",
          "prompt": "Calculate DANN AP minus pooled AP using 0.6934 and 0.7067.",
          "answer": -0.0133,
          "tolerance": 1e-05,
          "unit": "AP difference",
          "explanation": "0.6934 − 0.7067 = −0.0133.",
          "id": "results-q1",
          "lesson": "results"
        },
        {
          "type": "number",
          "prompt": "Five approaches each use three seeds. How many fits are there?",
          "answer": 15,
          "tolerance": 0,
          "unit": "fits",
          "explanation": "5×3 = 15.",
          "id": "results-q2",
          "lesson": "results"
        },
        {
          "type": "single",
          "prompt": "Which method has the highest mean AP in this short pilot?",
          "options": [
            "Kepler pretraining followed by TESS fine-tuning",
            "DANN",
            "Fresh Kepler-only",
            "Pooled training"
          ],
          "answer": 0,
          "explanation": "Fine-tuning has mean AP 0.7644 on this specific pilot audit.",
          "id": "results-q3",
          "lesson": "results"
        },
        {
          "type": "single",
          "prompt": "Why can’t we directly rank the 335-row benchmark against the 82-row pilot by AP?",
          "options": [
            "They use different evaluation cohorts and experiment contexts.",
            "AP is never useful.",
            "Both scores must be probabilities.",
            "The larger number is always the better architecture."
          ],
          "answer": 0,
          "explanation": "Cohort, prevalence, selection and training context differ.",
          "id": "results-q4",
          "lesson": "results"
        },
        {
          "type": "multi",
          "prompt": "Which conclusions are supported?",
          "options": [
            "All 15 planned short pilot fits completed",
            "DANN did not demonstrate a benefit here",
            "Convergence remains unestablished",
            "DANN can never work for astronomy"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The result has a defined scope and does not prove a universal negative.",
          "id": "results-q5",
          "lesson": "results"
        },
        {
          "type": "single",
          "prompt": "Do 44 comparison-scored saved proposals mean 44 new planets?",
          "options": [
            "No; they include real controls and synthetic/transformed controls.",
            "Yes, if all files exist.",
            "Yes, if DANN ran successfully.",
            "Only if their scores are averaged."
          ],
          "answer": 0,
          "explanation": "Operational inference checks and discovery counts are different things.",
          "id": "results-q6",
          "lesson": "results"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "The short pilot completed all 15 fits. On its shared audit, DANN did not demonstrate a benefit over pooling, so the reference CNN remains primary.",
      "pitfall": "Completion is an engineering milestone; convergence and scientific improvement are separate questions that require evidence.",
      "prerequisite": "contract"
    },
    {
      "id": "operations",
      "unit": "project",
      "order": 31,
      "title": "What runs when you close the browser?",
      "hook": "The website, watcher and comparison worker are separate processes. Learn which command answers which question.",
      "minutes": 35,
      "objectives": [
        "Separate serving, watching and model inference.",
        "Understand the configured watcher scope.",
        "Troubleshoot loading without launching duplicate servers."
      ],
      "sections": [
        {
          "title": "Three jobs run independently",
          "paragraphs": [
            "Picture three separate programs. The website answers your browser and displays saved records. The automatic watcher checks the configured archive targets and processes new eligible products. The comparison service adds experimental model scores to eligible completed candidates. Refreshing the browser asks the first program to show current records; it does not retrain a model or force an archive download. Closing the browser leaves separately running workers alone. Whether they keep running after you disconnect depends on how they were started, which is why we use named tmux sessions on a host that stays on.",
            "A process in a persistent tmux session can continue after an SSH terminal disconnects as long as the host and process remain running. Closing the browser is different from shutting down the server, logging out of an environment that kills processes, or losing network access needed for downloads."
          ]
        },
        {
          "title": "The actual configured scope",
          "paragraphs": [
            "At the 28 September snapshot, schema-2 archival discovery had selected 18 targets, with a six-hour configured interval and a two-product-per-cycle cap. The selection budget was full; archive_wide_complete was false. Two fixed known controls describe the earlier 23 September setup. New qualifying public SPOC products can be downloaded and processed within the saved policy; this is a bounded archival sample. The model-comparison worker polls completed local jobs about once per minute; it does not download the archive or retrain models.",
            "A manual watch-auto-check requests an immediate archive check under the configured policy. An unchanged archive can legitimately produce no new jobs. Inspect status and logs before assuming the website failed because the candidate list stayed the same."
          ]
        },
        {
          "title": "Separate a server problem from a forwarding problem",
          "paragraphs": [
            "Run commands from the repository root so module imports and relative paths resolve correctly. Address already in use means another process owns the requested port; inspect the existing service rather than blindly starting duplicates. In a remote VS Code session, your computer’s 127.0.0.1 is reached through port forwarding. A healthy remote server can still look unavailable through a stale or stopped local forward.",
            "Use the Ports panel to forward 8765 for Academy and 8766 for Research, then open the matching forwarded address. Refresh reloads displayed evidence; it is not a backup, Git push or model-training request. Copy only command text, not terminal prompts such as [user@host]$."
          ]
        },
        {
          "title": "A dated snapshot is not a live monitor",
          "paragraphs": [
            "This Academy compiles reviewed facts into local static assets; it never polls the research database. The 28 September captured watcher state was running/waiting with 18 selected targets. Its authoritative scorer identity is supported by completed 26 September model_score records. Heartbeats, selected targets, archive downloads and completed scores are different events. Inspect Research for live status, and preserve the original evidence when comparison workers append scores."
          ]
        }
      ],
      "example": {
        "title": "Refresh versus detect",
        "steps": [
          "Refresh the Research tab to display the current saved evidence.",
          "Run watch-auto-check to ask the configured watcher to check for new products now.",
          "Inspect status and logs to see whether anything new was available or processing failed."
        ],
        "answer": "These operations answer different questions. A successful check may find no new archive products."
      },
      "project": "Useful paths: outputs/research/server.log, outputs/research/automatic-watcher.log, outputs/research/logs/model-comparison.log and docs/website_guide.md. The Academy’s Project map separates dated evidence from live service status.",
      "sources": [],
      "quiz": [
        {
          "type": "single",
          "prompt": "What does refreshing the Research page primarily do?",
          "options": [
            "Reloads displayed saved evidence",
            "Retrains all models",
            "Pushes a new backup to GitHub",
            "Monitors every TESS star immediately"
          ],
          "answer": 0,
          "explanation": "Page refresh and background scientific workers are separate operations.",
          "id": "operations-q1",
          "lesson": "operations"
        },
        {
          "type": "single",
          "prompt": "What does Address already in use mean?",
          "options": [
            "Another process already owns the requested port.",
            "The model is untrained.",
            "All candidates were deleted.",
            "The telescope is offline."
          ],
          "answer": 0,
          "explanation": "Inspect the listening service and port forwarding before starting more processes.",
          "id": "operations-q2",
          "lesson": "operations"
        },
        {
          "type": "multi",
          "prompt": "What must remain available for a remote watcher to continue checking new products?",
          "options": [
            "The host and worker process",
            "Required archive network access",
            "Its configuration and writable data store",
            "An always-open Academy browser tab"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The browser is not the process doing background archive checks.",
          "id": "operations-q3",
          "lesson": "operations"
        },
        {
          "type": "number",
          "prompt": "The configured interval is six hours. Ignoring runtime and interruptions, how many scheduled checks fit in 24 hours?",
          "answer": 4,
          "tolerance": 0,
          "unit": "checks",
          "explanation": "24/6 = 4 checks under the simplified schedule.",
          "id": "operations-q4",
          "lesson": "operations"
        },
        {
          "type": "single",
          "prompt": "A successful manual check reports no new products. What follows?",
          "options": [
            "No qualifying new products were found under that configuration.",
            "The website must be broken.",
            "The sky has no planets.",
            "The CNN automatically changed its weights."
          ],
          "answer": 0,
          "explanation": "Archive availability and configuration can legitimately leave the candidate list unchanged.",
          "id": "operations-q5",
          "lesson": "operations"
        },
        {
          "type": "single",
          "prompt": "Which command checks the configured archive watcher now?",
          "options": [
            ".venv/bin/python -m scripts.research watch-auto-check",
            "git push",
            "A browser theme toggle",
            "Typing the terminal prompt itself"
          ],
          "answer": 0,
          "explanation": "watch-auto-check is the project’s immediate check command; it is distinct from serving or backing up.",
          "id": "operations-q6",
          "lesson": "operations"
        }
      ],
      "lab": null,
      "code": "# From your Thesis-Rojin checkout\n.venv/bin/python -m scripts.research status\n.venv/bin/python -m scripts.research watch-status\n# Explicitly request a new configured archive check:\n.venv/bin/python -m scripts.research watch-auto-check",
      "takeaway": "The browser, HTTP server and workers have different roles. Check the relevant service and its logs before restarting anything.",
      "pitfall": "Refreshing a tab updates the displayed records. Use Check for new data or watch-auto-check to request an archive check.",
      "prerequisite": "results"
    },
    {
      "id": "reproduce",
      "unit": "project",
      "order": 32,
      "title": "Results, logs and backups: preserve the evidence",
      "hook": "A Git push of source code does not automatically preserve the living database, review notes or model files.",
      "minutes": 35,
      "objectives": [
        "Distinguish logs, results and complete snapshots.",
        "Trace data and checkpoint provenance.",
        "Plan reproduction at the right level of effort."
      ],
      "sections": [
        {
          "title": "Know which evidence lives where",
          "paragraphs": [
            "To reproduce a result, first separate the things you need to preserve. Source code describes the procedure. Configuration files record its choices. Results and reports summarize what happened. The live research database stores candidate records and points to evidence files, which can include light curves, plots and model outputs. Logs help explain the sequence of events and failures. A Git push saves only committed files; it does not automatically collect an ignored database or the files referenced by it. Use the snapshot command when you want to preserve a complete live research state.",
            "The watcher writes live outputs automatically. It does not automatically create dated results snapshots or push to the Git remote. A fresh review or new data product is not protected by an older archive merely because both live in the same project."
          ]
        },
        {
          "title": "A reproducible snapshot includes references",
          "paragraphs": [
            "A database backup can preserve rows while leaving referenced files behind. The project’s vetting_snapshot tool collects the database and required referenced artifacts, including comparison checkpoints when model-comparison evidence points to them. It records checksums and supports verification and restoration. Verify an archive before relying on it, and test restoration into a separate destination rather than overwriting the live workspace.",
            "The existing results/vetting_snapshot_20260923 archive predates the appended DANN comparison evidence. The September 23 pilot’s compact result exports are separately reviewable. A backup covers only the records and files included in its own manifest; check a later backup’s contents before assuming it includes newer experiments. Archive size should be checked before deciding how to store it remotely."
          ]
        },
        {
          "title": "Reproduction has levels",
          "paragraphs": [
            "Reading saved reports is quick and needs no training. Replaying inference needs matching checkpoints, normalizer, input files and compatible code/environment. Re-running the controlled training experiment requires its data partitions, specification, seeds and compute budget. Repeating a blind archive search additionally depends on products and catalog versions that may have changed. State which level was reproduced.",
            "A checksum identifies file contents, not scientific correctness. Record commands, dependency versions and the meanings of metrics. The completed pilot verifies saved receipts on resume instead of silently retraining. Preserve negative results and original primary scores so future changes can be compared honestly."
          ]
        }
      ],
      "example": {
        "title": "What a new candidate requires for preservation",
        "steps": [
          "The watcher downloads a product and stores a candidate with evidence.",
          "A dated backup must collect the new database state and its referenced files.",
          "Verify the snapshot, review the intended files and storage size, then commit/push the chosen durable artifacts."
        ],
        "answer": "Refreshing a page or pushing source alone does not perform those backup steps."
      },
      "project": "The 23 September backup has its own dated scope; it is not evidence of a complete backup of the newer experiments. New result summaries live in results/fresh_classifier_audit_v1/ and results/ai_telescope_recovery_v1/. Export Academy progress separately from the research database.",
      "sources": [],
      "quiz": [
        {
          "type": "single",
          "prompt": "Does the watcher automatically create Git snapshots and push them?",
          "options": [
            "No; live updates and remote backup are separate operations.",
            "Yes, after every score.",
            "Only when the Academy is open.",
            "Yes, if DANN is enabled."
          ],
          "answer": 0,
          "explanation": "Dated backups and Git publication remain explicit operations.",
          "id": "reproduce-q1",
          "lesson": "reproduce"
        },
        {
          "type": "multi",
          "prompt": "What can a complete reproducible candidate backup need?",
          "options": [
            "Database records and review evidence",
            "Referenced light curves and prepared inputs",
            "Relevant model and normalization artifacts",
            "Only the current HTML screenshot"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "The database can refer to external files that must be preserved alongside its rows.",
          "id": "reproduce-q2",
          "lesson": "reproduce"
        },
        {
          "type": "single",
          "prompt": "Where should a restore test normally write?",
          "options": [
            "A separate destination",
            "Directly over the live database without checking",
            "Inside the active model file",
            "Into the browser’s address bar"
          ],
          "answer": 0,
          "explanation": "A separate restore verifies the archive without replacing the live state.",
          "id": "reproduce-q3",
          "lesson": "reproduce"
        },
        {
          "type": "single",
          "prompt": "What does a checksum establish?",
          "options": [
            "Whether file contents match the recorded bytes",
            "Whether a planet is confirmed",
            "Whether labels are unbiased",
            "Whether the model converged"
          ],
          "answer": 0,
          "explanation": "Integrity and scientific validity are different properties.",
          "id": "reproduce-q4",
          "lesson": "reproduce"
        },
        {
          "type": "single",
          "prompt": "Why might replaying inference take less time than reproducing training?",
          "options": [
            "It reuses fitted checkpoints instead of optimizing weights again.",
            "It needs no input data.",
            "It ignores preprocessing.",
            "It proves all future results automatically."
          ],
          "answer": 0,
          "explanation": "Inference is a forward computation using retained weights and compatible inputs.",
          "id": "reproduce-q5",
          "lesson": "reproduce"
        },
        {
          "type": "single",
          "prompt": "Where is Academy learning progress stored?",
          "options": [
            "In this browser, with explicit JSON export/import",
            "Automatically in the astronomical research database",
            "Automatically committed after every answer",
            "In the TESS archive"
          ],
          "answer": 0,
          "explanation": "The local course is separate from the research service and requires its own progress export for portability.",
          "id": "reproduce-q6",
          "lesson": "reproduce"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Save enough to trace a result from configuration and code through inputs, preprocessing and checkpoints to its evidence. Verify a snapshot before relying on it.",
      "pitfall": "A database backup can still be incomplete if its referenced files are missing. A Git push does not include ignored files automatically.",
      "prerequisite": "operations"
    },
    {
      "id": "injections",
      "unit": "research",
      "order": 33,
      "title": "Injection recovery and survey completeness",
      "hook": "To know what you miss, place controlled signals into realistic data and ask the entire pipeline to find them.",
      "minutes": 35,
      "objectives": [
        "Define a recovery criterion before testing.",
        "Distinguish completeness from reliability.",
        "Design realistic injections and negatives."
      ],
      "sections": [
        {
          "title": "Measure the selection function",
          "paragraphs": [
            "A search can miss real planets even when it works correctly on the examples you inspect. To measure what it tends to find, insert synthetic transits into representative data and run the same pipeline you plan to use scientifically. You know which events you inserted, so you can measure recovery by period, depth and observing conditions. This maps the selection function: how likely a signal with specified properties is to survive your procedure. Insert events before the processing stage you want to evaluate; adding them after detrending cannot measure whether detrending would have erased them.",
            "Inject before stages whose losses you want to include. Flux-level injection can test cleaning, search and classification, but may not capture pixel-level contamination or extraction effects. Pixel-level injection can address more upstream behavior but requires a more realistic image model and greater effort."
          ]
        },
        {
          "title": "Define success in advance",
          "paragraphs": [
            "A recovery rule can require the detected period and epoch to match within stated tolerances, sufficient event overlap and passage of the operational threshold. Decide whether harmonic matches count as full recovery, partial recovery or an alias category. If the rule is changed after inspecting failures, the measured success rate can become optimistic. Keep the injected truth separate from the detector’s accessible inputs.",
            "Use physical transit shapes and realistic noise where possible. Box injections are useful smoke tests but do not represent every transit morphology. Include shallow events and hard observing windows, not just obvious dips. Keep source-star groups independent between development and final evaluation."
          ]
        },
        {
          "title": "Recovery and false alarms answer different questions",
          "paragraphs": [
            "Injections measure what the pipeline finds when signals are present. Negative controls or an empirical null measure false detections when no injected target signal is present under a defined construction. Real “negative” stars can contain unknown planets, while transformed or scrambled data may destroy real noise correlations. Report these limitations instead of calling one negative set perfect truth.",
            "Reliability concerns the fraction of selected detections that are genuinely the desired class. It depends on prevalence and false-positive mechanisms as well as completeness. Four recovered injections do not determine the reliability of every alert in a large blind search."
          ]
        },
        {
          "title": "Three observations and one-to-one matching",
          "paragraphs": [
            "For each host, keep the original observation, a physically injected version and an inverted control. The original tells us whether a search already found an event at the injected time; subtract those matches before crediting incremental recovery. Inversion reverses dips and rises to stress-test alert behavior, but it cannot represent every astrophysical false positive.",
            "Match each predicted event to at most one injected event within half the true duration, and each injection to at most one prediction. This prevents multiple nearby detections from claiming the same transit. The original physical study had 90 registered hosts, 85 observable injections and 330 events; the fresh one has 99, 96 and 326. Keep every registered host in the primary denominator even when coverage is poor."
          ]
        },
        {
          "title": "Sensitivity and controls must travel together",
          "paragraphs": [
            "Fresh v3 at 0.86 recovers 21/99 hosts and 58/326 events, with 27 inverted alerts. At 0.90 it recovers 21/99 and 53/326, with 14 alerts over the same exposure: a 48.148% control reduction at the cost of five events. Equal host totals conceal one host gained and one lost. Every method misses all 25 registered 500-ppm injections. Among 33 single-transit hosts, v3 recovers four and TLS has three incidental event matches, not correct orbital periods. These failures define useful next experiments."
          ]
        }
      ],
      "example": {
        "title": "Read the historical six-injection pilot conservatively",
        "steps": [
          "Six box injections used two periods and three depths.",
          "Four were recovered; both 500 ppm injections were missed.",
          "Two of four negative controls passed a white-noise SNR reference cut."
        ],
        "answer": "This identifies useful failure cases. The tiny, selected control set cannot support a survey completeness map or a false-alarm-rate claim."
      },
      "project": "Completed physical studies retain 90 and 99 registered hosts in their denominators, including poorly observed injections. On the fresh cohort every method missed all 25 registered 500-ppm injections. Recovery of injected signals does not establish discovery of a real planet.",
      "sources": [
        "bls",
        "tls"
      ],
      "quiz": [
        {
          "type": "number",
          "prompt": "A prespecified injection set contains 80 signals and 60 meet the recovery rule. What is recovery in percent?",
          "answer": 75,
          "tolerance": 0.01,
          "unit": "%",
          "explanation": "60/80 = 75%, for that injection distribution and rule.",
          "id": "injections-q1",
          "lesson": "injections"
        },
        {
          "type": "multi",
          "prompt": "Which should be fixed before final injection evaluation?",
          "options": [
            "Period/epoch tolerance",
            "How harmonic detections count",
            "Operational threshold and selection rules",
            "Which failures to exclude after seeing results"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Post-hoc success definitions can bias estimated recovery.",
          "id": "injections-q2",
          "lesson": "injections"
        },
        {
          "type": "single",
          "prompt": "Can flux-level injection fully test pixel-extraction contamination?",
          "options": [
            "No; it bypasses some upstream image/extraction effects.",
            "Yes, automatically.",
            "Only if the model is DANN.",
            "It eliminates all noise."
          ],
          "answer": 0,
          "explanation": "The injection location determines which pipeline stages are tested.",
          "id": "injections-q3",
          "lesson": "injections"
        },
        {
          "type": "single",
          "prompt": "What does completeness primarily ask?",
          "options": [
            "What fraction of relevant signals are recovered?",
            "What fraction of selected alerts are real?",
            "How many HTML pages exist?",
            "How many model parameters fit in memory?"
          ],
          "answer": 0,
          "explanation": "Selected-alert purity is reliability/precision under a defined truth set; recovery addresses missed signals.",
          "id": "injections-q4",
          "lesson": "injections"
        },
        {
          "type": "single",
          "prompt": "What does the six-injection pilot justify?",
          "options": [
            "A limited operational check and concrete failure examples",
            "A precise full-survey completeness estimate",
            "A universal 66.7% planet probability",
            "A proof that every shallow signal is impossible"
          ],
          "answer": 0,
          "explanation": "Six selected injections cannot map the full parameter and noise space.",
          "id": "injections-q5",
          "lesson": "injections"
        },
        {
          "type": "single",
          "prompt": "Why preserve time correlation in an empirical null when possible?",
          "options": [
            "Destroying it can make false alarms unrealistically easy to reject.",
            "Correlation is always a planet.",
            "The timestamps are irrelevant.",
            "It ensures zero false positives."
          ],
          "answer": 0,
          "explanation": "Real correlated noise can generate transit-like search peaks.",
          "id": "injections-q6",
          "lesson": "injections"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Injection recovery measures which planted signals survive a specified pipeline. Negative controls measure a different issue: how often the procedure produces false alerts.",
      "pitfall": "A few simple box injections are useful engineering checks, but they do not establish completeness for all physical transits or observing conditions.",
      "prerequisite": "reproduce"
    },
    {
      "id": "ablation",
      "unit": "research",
      "order": 34,
      "title": "Ablations, uncertainty and fair experiments",
      "hook": "A better number is the beginning of an explanation. Isolate which change caused it.",
      "minutes": 35,
      "objectives": [
        "Design controlled ablations.",
        "Distinguish paired uncertainty and seed variability.",
        "Choose primary metrics and compute budgets before testing."
      ],
      "sections": [
        {
          "title": "Change one scientific factor at a time",
          "paragraphs": [
            "Suppose your new model improves after you add a coverage mask, change the architecture and train for twice as long. Which change caused the improvement? An ablation separates those possibilities by changing one scientific factor while keeping the comparison otherwise matched. For example, compare the same model with and without the mask, using the same allowed data, split and evaluation rules. Some changes require their own tuning, so record that budget too. The goal is a comparison whose outcome supports a specific explanation, rather than a contest between two bundles of unrelated changes.",
            "An ablation may change optimization difficulty or effective capacity, so interpretation still needs care. If removing a module also halves training time, decide whether the comparison is about a fixed compute budget, fixed data exposure or best tuned performance. State which question you are answering."
          ]
        },
        {
          "title": "Use paired comparisons when predictions share cases",
          "paragraphs": [
            "When two methods score the same held-out stars, resample the same groups for both and compute the metric difference in each bootstrap sample. This preserves pairing and focuses uncertainty on the comparison. Respect group dependence and handle samples with no positives under a declared policy. A confidence interval including zero does not prove the methods identical; it means the chosen procedure did not exclude a zero difference.",
            "Seed spread describes variation across trained models, while cohort resampling describes sensitivity to the evaluated examples. Reporting one does not replace the other. Very small cohorts can make both estimates unstable."
          ]
        },
        {
          "title": "Decide what counts as useful before looking",
          "paragraphs": [
            "A primary endpoint might be recall at a fixed number of candidates sent to human vetters. Safety or secondary metrics might include shallow-transit recovery, false-alert count, subgroup behavior and runtime. Set a minimum useful effect and stopping or failure criteria before audit evaluation. This reduces the temptation to find a favorable metric after seeing results.",
            "Use tuning data for model choices and preserve a final evaluation boundary. Log failed runs, compute usage and excluded cases. If the available budget supports only a pilot, call it a pilot and report what question remains unanswered."
          ]
        },
        {
          "title": "Separate a calibration fix from a sensitivity gain",
          "paragraphs": [
            "Recovery thresholds were frozen on 78 separate calibration hosts. Testing exact observed score boundaries, with tied events counted together, avoids missing an operating point merely because a threshold grid is coarse. The new rule also uses a 50% transfer margin and Poisson/host-bootstrap upper estimates. That conservatism can select a high threshold: exact-boundary BLS recovered 0/99 hosts here. Fixing grid mechanics did not solve sensitivity.",
            "The single-event search compares local dips with surrounding sidebands across 0.5–12-hour durations, avoiding a requirement for a repeating period. Its hybrid with the neural detector splits the control budget between searches. It recovered only 5/99 hosts and is rejected. Neural weights were unchanged; claim only the implemented search/calibration change and the measured outcome."
          ]
        }
      ],
      "example": {
        "title": "Isolate the adversary",
        "steps": [
          "Train pooled and DANN models with the same backbone, features, grouped data and allowed update budget.",
          "Prespecify seeds and λ choices using tuning data only.",
          "Evaluate paired audit predictions and inspect learning curves."
        ],
        "answer": "A gain would support this adversarial setup under these conditions; a loss identifies a result to explain, not one to hide."
      },
      "project": "More machinery did not automatically help: cross-fitted competence selection returned routing strength zero, and the fresh detector hybrid recovered only 5/99 hosts. Keep rejected experiments visible and compare the mechanism at a fixed control budget.",
      "sources": [
        "dann"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "Which ablation most directly tests the domain-adversarial contribution?",
          "options": [
            "Compare against matched pooling without gradient reversal.",
            "Change the data split and architecture simultaneously.",
            "Evaluate only the best DANN example.",
            "Remove difficult negatives from DANN’s test."
          ],
          "answer": 0,
          "explanation": "Matching other factors isolates the adversarial training contribution as far as the design permits.",
          "id": "ablation-q1",
          "lesson": "ablation"
        },
        {
          "type": "single",
          "prompt": "Why use the same resampled groups for both methods in a paired bootstrap?",
          "options": [
            "To preserve the comparison on matched evaluation cases",
            "To guarantee a positive difference",
            "To increase the physical number of stars",
            "To train both methods on the audit"
          ],
          "answer": 0,
          "explanation": "Pairing controls shared cohort variation when estimating a metric difference.",
          "id": "ablation-q2",
          "lesson": "ablation"
        },
        {
          "type": "multi",
          "prompt": "Which should be prespecified for a confirmatory comparison?",
          "options": [
            "Primary metric and meaningful effect size",
            "Data splits and seeds",
            "Compute and tuning budget",
            "Whichever metric looks best after audit inspection"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Post-hoc metric selection weakens the interpretation of a favorable result.",
          "id": "ablation-q3",
          "lesson": "ablation"
        },
        {
          "type": "single",
          "prompt": "A confidence interval for a difference includes zero. What is justified?",
          "options": [
            "The analysis did not rule out zero under its assumptions.",
            "The methods are proven identical.",
            "Both methods are invalid.",
            "The better point estimate is guaranteed superior."
          ],
          "answer": 0,
          "explanation": "Failure to exclude zero is not proof of equivalence.",
          "id": "ablation-q4",
          "lesson": "ablation"
        },
        {
          "type": "number",
          "prompt": "Method A has recall 0.80 and B has 0.75 on the same cohort. What is A−B in percentage points?",
          "answer": 5,
          "tolerance": 0.001,
          "unit": "percentage points",
          "explanation": "0.80−0.75=0.05, or 5 percentage points, not a 5% relative increase.",
          "id": "ablation-q5",
          "lesson": "ablation"
        },
        {
          "type": "single",
          "prompt": "A component wins only after ten extra tuning rounds unavailable to its baseline. What must be acknowledged?",
          "options": [
            "The unequal tuning budget is a possible explanation for the gain.",
            "The component is proven unique.",
            "Tuning never affects comparisons.",
            "The audit is automatically larger."
          ],
          "answer": 0,
          "explanation": "Search effort is part of the experimental resource budget.",
          "id": "ablation-q6",
          "lesson": "ablation"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "Make a comparison answer one scientific question. Pair predictions on the same audit cases and preserve the grouping structure when estimating uncertainty.",
      "pitfall": "Seed variation and uncertainty across stars are different. Reporting one does not automatically account for the other.",
      "prerequisite": "injections"
    },
    {
      "id": "papers",
      "unit": "research",
      "order": 35,
      "title": "Read a paper and find a defensible gap",
      "hook": "The research question is not “has anyone used AI?” It is “what remains unresolved under a clearly stated evaluation?”",
      "minutes": 35,
      "objectives": [
        "Extract a paper’s task, evidence and limitations.",
        "Distinguish novelty from usefulness.",
        "Form a literature-grounded, falsifiable gap."
      ],
      "sections": [
        {
          "title": "Read the contract before the headline",
          "paragraphs": [
            "When you open a paper, begin with what goes in and what comes out. Does the model search raw observations, classify detected events or validate selected candidates? Next identify the labels, the unit of splitting, the inputs and the evaluation population. These define the scientific contract: the precise task its reported performance describes. Trace a headline number back to its denominator and selection rules. You can then ask whether the method addresses the same problem as your project, instead of comparing two percentages that refer to different tasks.",
            "Look at tables of failures and ablations, not just architecture diagrams. Ask whether code, data splits and model artifacts are available, and whether the stated task can be reproduced with them. Check manuscript version and publication status; the newest abstract may differ from an older implementation."
          ]
        },
        {
          "title": "Useful is not the same as first-ever",
          "paragraphs": [
            "Reproduction, careful negative results, reliable tooling, new datasets and rigorous evaluation can be valuable contributions. Novelty is a claim about prior work and needs a focused literature comparison. CNNs, Transformers, domain adversaries and automated vetting already exist. Combining their names does not establish an original method.",
            "A precise gap could be that a method’s cross-mission performance has not been evaluated under a particular blind-search selection process with grouped controls and realistic injections. That is a candidate gap to investigate, not a fact established merely because this repository lacks the experiment."
          ]
        },
        {
          "title": "Build an evidence matrix",
          "paragraphs": [
            "For each close paper, record task, inputs, domains, labels, split unit, metrics, compute budget, code availability and limitations. Compare methods that address the same endpoint. Trace citations backward for foundational approaches and forward for subsequent results. Search terms should describe the scientific failure, not only a proposed architecture.",
            "Convert the gap into a falsifiable statement: an intervention should improve a prespecified endpoint under controlled conditions by a meaningful amount. State what result would refute it. A hypothesis that explains every possible outcome is not useful for choosing the next experiment."
          ]
        }
      ],
      "example": {
        "title": "A better research question",
        "steps": [
          "Broad: “Use a Transformer and DANN to find new planets.”",
          "Narrow: “Does explicit coverage masking improve shallow-signal recall at a fixed vetting budget on unseen TESS stars compared with matched pooling?”",
          "Check prior work and define the data, masks, baseline and minimum effect before running."
        ],
        "answer": "The narrow question identifies a mechanism and measurable endpoint without asserting novelty in advance."
      },
      "project": "Use the current project evidence map alongside primary papers. The negative DANN, routing and hybrid results constrain the next hypothesis. Automated classification alone is not novelty, and no cross-paper leaderboard is justified without matched tasks and populations.",
      "sources": [
        "astro",
        "exominer",
        "transformer",
        "raven26",
        "hunters"
      ],
      "quiz": [
        {
          "type": "single",
          "prompt": "What should be identified before comparing two papers’ AUC values?",
          "options": [
            "Task, labels, inputs and evaluation population",
            "Only the publication month",
            "Only the number of authors",
            "Only the GPU model"
          ],
          "answer": 0,
          "explanation": "Metric meaning depends on the scientific and statistical contract.",
          "id": "papers-q1",
          "lesson": "papers"
        },
        {
          "type": "multi",
          "prompt": "Which can be valuable research contributions without a new neural architecture?",
          "options": [
            "A rigorous reproducibility study",
            "A well-characterized dataset or benchmark",
            "An informative controlled negative result",
            "An unsupported claim of being first"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Value can come from evidence and methodology; unsupported novelty language adds none.",
          "id": "papers-q2",
          "lesson": "papers"
        },
        {
          "type": "single",
          "prompt": "Which is a falsifiable hypothesis?",
          "options": [
            "Coverage masking improves recall by at least a prespecified margin at a fixed review budget on a locked cohort.",
            "Our model will be interesting no matter what happens.",
            "AI always finds planets.",
            "Any score change proves success."
          ],
          "answer": 0,
          "explanation": "A falsifiable hypothesis has an endpoint and an outcome that can fail to meet it.",
          "id": "papers-q3",
          "lesson": "papers"
        },
        {
          "type": "single",
          "prompt": "Your repository lacks a feature. Does that establish a gap in the literature?",
          "options": [
            "No; other published systems may already address it.",
            "Yes, by definition.",
            "Only if the feature uses attention.",
            "Yes, if it is added to the README."
          ],
          "answer": 0,
          "explanation": "A local implementation gap and a scientific literature gap are different things.",
          "id": "papers-q4",
          "lesson": "papers"
        },
        {
          "type": "single",
          "prompt": "Why record the unit of prediction?",
          "options": [
            "Cadence-, event-, star- and system-level metrics answer different questions.",
            "It determines whether decimals are allowed.",
            "It replaces the positive label.",
            "It makes every sample independent."
          ],
          "answer": 0,
          "explanation": "The prediction unit shapes label construction, dependence and metric interpretation.",
          "id": "papers-q5",
          "lesson": "papers"
        },
        {
          "type": "single",
          "prompt": "Which search is more useful for evaluating the masking idea?",
          "options": [
            "Prior work on observing-window gaps, transit recovery and missing-data representations",
            "Only papers whose titles contain our repository name",
            "Only the highest-accuracy abstract",
            "Only generic AI marketing pages"
          ],
          "answer": 0,
          "explanation": "Search the mechanism and scientific failure as well as the architecture.",
          "id": "papers-q6",
          "lesson": "papers"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "A useful research gap identifies a limitation, a testable proposed change and an appropriate comparison. Record the evidence that would change your conclusion.",
      "pitfall": "Combining familiar model names does not establish novelty. First check whether the specific question and method have already been studied.",
      "prerequisite": "ablation"
    },
    {
      "id": "capstone",
      "unit": "research",
      "order": 36,
      "title": "Capstone: choose a study worth running",
      "hook": "Make the decisions a reviewer will ask about. Every course assessment is graded from explicit choices or calculations.",
      "minutes": 35,
      "objectives": [
        "Choose a coherent hypothesis and baseline.",
        "Select a leakage-safe evaluation and failure criterion.",
        "Connect a research result to a bounded claim."
      ],
      "sections": [
        {
          "title": "Your scenario",
          "paragraphs": [
            "You now have the pieces to design a study around this repository. There is a working bounded watcher, a frozen CNN reference, eleven comparison experts, a small fresh classifier audit and two completed physical detector studies. They test different tasks and leave specific failures unresolved. Your task is to choose one question the existing evidence does not settle and design a fair way to test it. A useful study might target shallow signals or incomplete observing coverage, but it needs a measurable outcome and a meaningful comparator. The aim is to make a result interpretable whether the proposed method improves performance or fails to do so.",
            "One plausible study is to add explicit coverage or quality information and test whether it helps a matched model preserve shallow-event sensitivity. Another is to add reliable source-location diagnostics. Choose one mechanism initially; adding every idea at once makes success or failure hard to interpret."
          ]
        },
        {
          "title": "Choose a complete experimental contract",
          "paragraphs": [
            "Use grouped development data, a separate calibration role if needed and an untouched final cohort. Include strong task-matched baselines: static v4 and variability for candidate classification; calibrated v3 and independently calibrated TLS/BLS for event recovery. Match inputs, search limits and tuning budgets. Prespecify a primary endpoint such as injection recovery at a fixed candidate-review budget, plus false-alert and subgroup checks. Count all training and tuning costs.",
            "Ablate the new information or objective. Retain raw data, configuration, seeds, model hashes and all results. If a method improves AP while worsening shallow-event recovery at the chosen operating point, the answer depends on the declared objective; do not redefine success after seeing the audit."
          ]
        },
        {
          "title": "Decide the claim before choosing the headline",
          "paragraphs": [
            "A successful controlled study can support a bounded improvement on its evaluated population. It does not automatically establish general superiority, a novel architecture or a new planet. A failed hypothesis can still reveal a useful limitation if the design and evidence are strong. Candidate discoveries need their own physical and catalog vetting chain.",
            "Passing this course’s objective checks shows progress in the concepts tested. It is not a professional credential or proof of independent research expertise. The next stage is reproducing an analysis, reviewing real cases with an experienced researcher and defending an experiment against the primary literature. Use the final exam to locate remaining conceptual gaps, then apply the methods to real evidence."
          ]
        },
        {
          "title": "Three possible experiments, not three results",
          "paragraphs": [
            "For shallow events, freeze a new 500-ppm injection cohort and compare one change in detrending or representation against calibrated v3 and TLS at a prespecified control budget. Report depth-stratified recovery even if the overall metric improves. For contamination, add off-target and eclipsing-binary cases and test source localization rather than assuming an on-target PSF injection proves host identity.",
            "For candidate classification, acquire a larger independent cohort with enough positive labels and document which products are unavailable. Compare frozen nonlinear, static and single experts with matched calibration. Keep multi-sector robustness and review workload as explicit endpoints if they motivate the study. These are proposals; none has a measured improvement yet."
          ]
        }
      ],
      "example": {
        "title": "A study with a clear stop rule",
        "steps": [
          "Hypothesis: coverage masks improve shallow-injection recall at a fixed review budget on unseen TESS groups.",
          "Baseline: matched pooled/fine-tuned models with equal allowed data and tuning; ablation: remove only the mask.",
          "Stop or revise if the prespecified improvement is absent or false-alert workload exceeds the allowed limit."
        ],
        "answer": "The study can fail cleanly, which makes a successful result interpretable."
      },
      "project": "Choose a remaining failure: 500-ppm events, single-transit sensitivity, background/binary rejection, multi-sector robustness or a larger independent classifier cohort. Prespecify controls and decision criteria. None of these proposed improvements has been demonstrated by planning it.",
      "sources": [],
      "quiz": [
        {
          "type": "single",
          "prompt": "Which is the strongest starting hypothesis for this scenario?",
          "options": [
            "Explicit coverage information improves a defined shallow-signal endpoint under a controlled comparison.",
            "A newer architecture is always better.",
            "Every unmatched dip is a planet.",
            "Any AP increase on any cohort proves success."
          ],
          "answer": 0,
          "explanation": "A mechanism, endpoint and controlled setting make the hypothesis testable.",
          "id": "capstone-q1",
          "lesson": "capstone"
        },
        {
          "type": "multi",
          "prompt": "Which belong in the study before final evaluation?",
          "options": [
            "A strong matched baseline",
            "Grouped independent evaluation and a fixed endpoint",
            "An ablation and failure rule",
            "Permission to redefine success after every result"
          ],
          "answer": [
            0,
            1,
            2
          ],
          "explanation": "Prespecified comparisons make the conclusion interpretable.",
          "id": "capstone-q2",
          "lesson": "capstone"
        },
        {
          "type": "single",
          "prompt": "The new method raises AP but fails the declared shallow-recovery endpoint. What should the primary conclusion say?",
          "options": [
            "It failed the primary endpoint; report the AP change as a secondary result.",
            "It succeeded because any improved metric counts.",
            "Delete the original endpoint.",
            "Select a different test set."
          ],
          "answer": 0,
          "explanation": "Primary and secondary outcomes must remain distinct after results are known.",
          "id": "capstone-q3",
          "lesson": "capstone"
        },
        {
          "type": "single",
          "prompt": "When should a new model replace the operational reference?",
          "options": [
            "After relevant held-out and operational evidence supports the intended use",
            "As soon as training finishes",
            "When its name includes Transformer",
            "When one unmatched score increases"
          ],
          "answer": 0,
          "explanation": "Operational promotion needs evidence of useful behavior, not merely a completed fit.",
          "id": "capstone-q4",
          "lesson": "capstone"
        },
        {
          "type": "single",
          "prompt": "A careful negative result has which value?",
          "options": [
            "It can constrain a hypothesis and guide the next experiment.",
            "None; only positive claims belong in research.",
            "It proves every related method impossible.",
            "It should always be hidden."
          ],
          "answer": 0,
          "explanation": "Negative evidence is useful when the experiment validly tests a stated question.",
          "id": "capstone-q5",
          "lesson": "capstone"
        },
        {
          "type": "single",
          "prompt": "What does completing the course demonstrate?",
          "options": [
            "Mastery of the tested material, with further practice and research still needed",
            "Guaranteed expert status in all exoplanet research",
            "A validated new planet",
            "An automatic scientific publication"
          ],
          "answer": 0,
          "explanation": "Course grades are learning feedback, not substitutes for research practice and external review.",
          "id": "capstone-q6",
          "lesson": "capstone"
        }
      ],
      "lab": null,
      "code": null,
      "takeaway": "A strong plan states the hypothesis, allowed data, baseline, audit, success criterion and stop rule before running. A clear negative result can still answer the question.",
      "pitfall": "Do not keep changing the definition of success after seeing the audit. That turns the evaluation into another tuning exercise.",
      "prerequisite": "papers"
    }
  ],
  "sources": [
    {
      "id": "tess",
      "title": "TESS science and observing",
      "url": "https://heasarc.gsfc.nasa.gov/docs/tess/",
      "year": "Living documentation",
      "status": "NASA / HEASARC",
      "takeaway": "Mission, products and observing context. Inspect individual product metadata for cadence and processing version.",
      "checked": "2026-09-23"
    },
    {
      "id": "bls",
      "title": "Astropy BoxLeastSquares",
      "url": "https://docs.astropy.org/en/stable/timeseries/bls.html",
      "year": "Living documentation",
      "status": "Official implementation",
      "takeaway": "How to evaluate a period, duration and transit-time search; the statistic depends on the selected objective.",
      "checked": "2026-09-23"
    },
    {
      "id": "tls",
      "title": "Hippke & Heller · Transit Least Squares",
      "url": "https://arxiv.org/abs/1901.02015",
      "year": "2019",
      "status": "Research paper",
      "takeaway": "Searches with transit-shaped templates that include ingress, egress and limb darkening. Compare recovery and runtime on the same data.",
      "checked": "2026-09-23"
    },
    {
      "id": "astro",
      "title": "Shallue & Vanderburg · Identifying exoplanets with deep learning",
      "url": "https://arxiv.org/abs/1712.05044",
      "year": "2018",
      "status": "Research paper",
      "takeaway": "A foundational global/local light-curve CNN. Read the input construction and train/test separation before comparing metrics.",
      "checked": "2026-09-23"
    },
    {
      "id": "dann",
      "title": "Ganin et al. · Domain-adversarial training of neural networks",
      "url": "https://jmlr.org/papers/v17/15-239.html",
      "year": "2016",
      "status": "JMLR research paper",
      "takeaway": "A gradient reversal layer encourages a representation that supports the task while confusing a domain classifier. Alignment is not a guarantee of target improvement.",
      "checked": "2026-09-23"
    },
    {
      "id": "cal",
      "title": "Guo et al. · On calibration of modern neural networks",
      "url": "https://proceedings.mlr.press/v70/guo17a.html",
      "year": "2017",
      "status": "ICML research paper",
      "takeaway": "Temperature scaling is a post-training calibration method. Its evaluation needs separate data and a clearly defined target population.",
      "checked": "2026-09-23"
    },
    {
      "id": "crowd",
      "title": "Understanding crowding in TESS",
      "url": "https://heasarc.gsfc.nasa.gov/docs/tess/UnderstandingCrowdingv2.html",
      "year": "Living documentation",
      "status": "NASA / HEASARC",
      "takeaway": "Aperture contamination and nearby sources affect the inferred depth and host identity.",
      "checked": "2026-09-23"
    },
    {
      "id": "dave",
      "title": "Kostov et al. · DAVE vetting pipeline",
      "url": "https://arxiv.org/abs/1901.07459",
      "year": "2019",
      "status": "Research paper",
      "takeaway": "Automated diagnostic tests support human vetting; investigate morphology and source location instead of trusting one score.",
      "checked": "2026-09-23"
    },
    {
      "id": "triage",
      "title": "Tey et al. · Astronet-Triage-v2",
      "url": "https://arxiv.org/abs/2301.01371",
      "year": "2023",
      "status": "Research paper",
      "takeaway": "Triage separates eclipsing/transiting signals from other variability in TESS FFI searches. Its positive class includes stellar eclipses; its precision is not planet purity.",
      "checked": "2026-09-23"
    },
    {
      "id": "exominer",
      "title": "Valizadegan et al. · ExoMiner++",
      "url": "https://arxiv.org/abs/2502.09790",
      "year": "2025",
      "status": "Published · AJ 170(5), 287",
      "takeaway": "Diagnostic-rich classification of detected signals; 7,330 candidate-classified TCEs are not confirmed new planets.",
      "checked": "2026-09-28",
      "fullText": "https://arxiv.org/html/2502.09790v4",
      "submitted": "2025-02-13",
      "revised": "2025-05-19",
      "version": "v4",
      "evidenceType": "Candidate vetting and catalog",
      "accessNote": "Abstract/full-text unlabeled-TCE totals differ by one; the tour uses about 148,000.",
      "published": "2025-11-03",
      "earlyOnline": "2025-10-28",
      "publicationUrl": "https://research.birmingham.ac.uk/en/publications/exominer-enhanced-transit-classification-and-a-new-vetting-catalo/",
      "accessed": "2026-09-28"
    },
    {
      "id": "transformer",
      "title": "Salinas et al. · Transformer search of TESS light curves",
      "url": "https://arxiv.org/abs/2502.07542",
      "year": "2025",
      "status": "Published · MNRAS 538(3)",
      "takeaway": "Unfolded flux, background and centroids support a search yielding 214 candidate systems, not 214 confirmed planets.",
      "checked": "2026-09-28",
      "submitted": "2025-02-11",
      "revised": "2025-03-07",
      "version": "v2",
      "evidenceType": "Ephemeris-free candidate search",
      "issueDate": "2025-04",
      "accessed": "2026-09-28"
    },
    {
      "id": "raven",
      "title": "Hadjigeorghiou et al. · RAVEN framework",
      "url": "https://arxiv.org/abs/2509.17645",
      "year": "2025",
      "status": "Submitted to MNRAS in inspected record",
      "takeaway": "Classifiers and priors compare planetary and false-positive scenarios within a stated selection.",
      "checked": "2026-09-28",
      "submitted": "2025-09-22",
      "version": "v1",
      "evidenceType": "Scenario-based validation framework",
      "accessed": "2026-09-28"
    },
    {
      "id": "raven26",
      "title": "Lafarga et al. · TESS-SPOC FFI search with RAVEN",
      "url": "https://arxiv.org/abs/2603.22597",
      "year": "2026",
      "status": "Published · MNRAS 548(3), stag512",
      "takeaway": "118 newly statistically validated planets, including 31 newly detected here, are distinct from over 2,000 unvalidated candidates.",
      "checked": "2026-09-28",
      "submitted": "2026-03-23",
      "revised": "2026-04-24",
      "version": "v2",
      "evidenceType": "Survey search and statistical validation",
      "published": "2026-03-25",
      "issueDate": "2026-05",
      "publicationUrl": "https://academic.oup.com/mnras/article/548/3/stag512/8528996",
      "accessed": "2026-09-28"
    },
    {
      "id": "lightkurve",
      "title": "Lightkurve tutorials",
      "url": "https://lightkurve.github.io/lightkurve/tutorials/",
      "year": "Living documentation",
      "status": "Official project tutorials",
      "takeaway": "Worked Python workflows for mission light curves, pixels, flattening and transit searches. Record package versions when reproducing.",
      "checked": "2026-09-23"
    },
    {
      "id": "numpy",
      "title": "NumPy absolute beginners guide",
      "url": "https://numpy.org/doc/stable/user/absolute_beginners.html",
      "year": "Living documentation",
      "status": "Official documentation",
      "takeaway": "Arrays, shapes, indexing and vectorized operations underlying the project’s preprocessing and model inputs.",
      "checked": "2026-09-23"
    },
    {
      "id": "torch",
      "title": "PyTorch autograd introduction",
      "url": "https://docs.pytorch.org/tutorials/beginner/blitz/autograd_tutorial.html",
      "year": "Living documentation",
      "status": "Official documentation",
      "takeaway": "How tensors record a computation graph and gradients drive parameter updates.",
      "checked": "2026-09-23"
    },
    {
      "id": "attention",
      "title": "Vaswani et al. · Attention Is All You Need",
      "url": "https://arxiv.org/abs/1706.03762",
      "year": "2017",
      "status": "Research paper",
      "takeaway": "Defines attention and the Transformer architecture; applying it to astronomy still requires appropriate time encoding, masks, data and evaluation.",
      "checked": "2026-09-23"
    },
    {
      "id": "exofop",
      "title": "ExoFOP-TESS help and contribution requirements",
      "url": "https://exofop.ipac.caltech.edu/tess/help.php",
      "year": "Checked 2026-09-23",
      "status": "Official service documentation",
      "takeaway": "Check current upload permissions and Community Candidate publication requirements before submission. A catalog entry is not confirmation.",
      "checked": "2026-09-23",
      "accessNote": "Fresh access on 2026-09-28 was unsuccessful; consult the current official requirements."
    },
    {
      "id": "exoveil",
      "title": "Priyanshu · EXOVEIL",
      "url": "https://arxiv.org/abs/2606.02778",
      "year": "2026",
      "status": "Preprint; no journal acceptance established",
      "takeaway": "47/47 selected TESS recoveries and 179 Kepler transit-like anomalies are separate evaluations, not survey completeness or confirmed discoveries.",
      "checked": "2026-09-28",
      "fullText": "https://arxiv.org/html/2606.02778v3",
      "submitted": "2026-06-01",
      "revised": "2026-06-10",
      "version": "v3",
      "evidenceType": "Reported search and selected-control recovery",
      "accessed": "2026-09-28"
    },
    {
      "id": "hunters",
      "title": "Eldin · Astro-Hunters",
      "url": "https://arxiv.org/abs/2608.18172",
      "year": "2026",
      "status": "Preprint; no journal acceptance established",
      "takeaway": "189,279 cadences from twelve hosts: label circularity and time conversion can dominate architecture differences.",
      "checked": "2026-09-28",
      "fullText": "https://arxiv.org/html/2608.18172v1",
      "submitted": "2026-08-17",
      "version": "v1",
      "evidenceType": "Label-provenance ablation",
      "accessed": "2026-09-28"
    },
    {
      "id": "conformal",
      "title": "Angelopoulos & Bates · A gentle introduction to conformal prediction",
      "url": "https://arxiv.org/abs/2107.07511",
      "year": "2021",
      "status": "Methods tutorial",
      "takeaway": "Prediction sets or intervals can have marginal coverage under assumptions such as exchangeability. Distribution shift and conditional coverage require care.",
      "checked": "2026-09-23"
    },
    {
      "id": "btsbot",
      "title": "Rehemtulla et al. · BTSbot architecture",
      "url": "https://arxiv.org/abs/2401.15167",
      "year": "2024",
      "submitted": "2024-01-26",
      "status": "Published · ApJ 972, 7",
      "evidenceType": "Model and operational workflow",
      "takeaway": "Image and scalar evidence can drive a defined bright-transient follow-up policy.",
      "published": "2024-08-21",
      "issueDate": "2024-09",
      "publicationUrl": "https://sites.astro.caltech.edu/ztf/bts/bts.php",
      "fullText": "https://researchonline.ljmu.ac.uk/24472/1/The%20Zwicky%20Transient%20Facility%20Bright%20Transient%20Survey.%20III.%20BTSbot%20Automated%20Identification%20and%20Follow-up%20of%20Bright%20Transients%20with%20Deep%20Learning.pdf",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "btsbot-nearby",
      "title": "Rehemtulla et al. · BTSbot-nearby and SN 2024jlf",
      "url": "https://arxiv.org/abs/2501.18686",
      "fullText": "https://arxiv.org/html/2501.18686v2",
      "year": "2025 paper / 2024 event",
      "submitted": "2025-01-30",
      "revised": "2025-04-21",
      "version": "v2",
      "eventDate": "2024-05-28",
      "status": "Published · ApJ 985, 241",
      "evidenceType": "Demonstrated autonomous follow-up",
      "takeaway": "Seven minutes measures request-to-observation latency, not time since explosion.",
      "published": "2025-05-29",
      "issueDate": "2025-06",
      "publicationUrl": "https://researchdiscovery.drexel.edu/esploro/outputs/journalArticle/The-BTSbot-nearby-Discovery-of-SN-2024jlf/991022055174904721",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "btsbot-2023",
      "title": "Northwestern · the SN 2023tyk automated chain",
      "url": "https://news.northwestern.edu/stories/2023/10/first-supernova-detected-confirmed-classified-and-shared-by-ai",
      "year": "2023 historical context",
      "published": "2023-10-13",
      "eventDate": "2023-10-03 to 2023-10-07",
      "status": "Responsible-institution report",
      "evidenceType": "Historical operational milestone",
      "takeaway": "Detection, selection, spectroscopy, classification and reporting were linked stages.",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "rubin-alerts",
      "title": "Rubin Observatory · first scientific alerts",
      "url": "https://rubinobservatory.org/news/first-alerts",
      "year": "2026",
      "published": "2026-02-25",
      "eventDate": "2026-02-24",
      "status": "Official observatory release",
      "evidenceType": "Measured alert milestone",
      "takeaway": "800,000 alerts in the reported night; seven million nightly was an eventual forecast.",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "rubin-brokers",
      "title": "Rubin Observatory · alerts and brokers",
      "url": "https://rubinobservatory.org/for-scientists/data-products/alerts-and-brokers",
      "year": "Living documentation",
      "updated": "2026-07-03",
      "status": "Official observatory documentation",
      "evidenceType": "System roles, not comparative performance",
      "takeaway": "Brokers enrich and select alert packets; follow-up observations require further action.",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "exominer-nasa",
      "title": "NASA · ExoMiner++ moves into TESS data",
      "url": "https://science.nasa.gov/open-science/deep-learning-exoplanets-tess/",
      "year": "2026 coverage of 2025 work",
      "published": "2026-01-22",
      "status": "Responsible-institution article",
      "evidenceType": "Publication context and follow-up caveat",
      "takeaway": "The news date is distinct from the model's manuscript date; candidates still need follow-up.",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "desi-vae",
      "title": "Nicolaou et al. · anomalous DESI spectra with a VAE",
      "url": "https://arxiv.org/abs/2506.17376",
      "fullText": "https://arxiv.org/html/2506.17376v2",
      "year": "2025–2026",
      "submitted": "2025-06-20",
      "revised": "2026-03-11",
      "published": "2026-01-07",
      "version": "v2",
      "status": "Published · MNRAS 547(2)",
      "evidenceType": "Anomaly detection with human review",
      "takeaway": "Reconstruction and latent-space outliers include artifacts as well as physically unusual spectra.",
      "issueDate": "2026-04",
      "publicationUrl": "https://academic.oup.com/mnras/article/547/2/stag010/8416432",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "galaxy-byol",
      "title": "Mohale & Lochner · self-supervised galaxy representations",
      "url": "https://arxiv.org/abs/2311.14157",
      "year": "2023–2024 context",
      "submitted": "2023-11-23",
      "revised": "2024-04-19",
      "status": "Published · MNRAS 530(1)",
      "evidenceType": "Image representation and anomaly search",
      "takeaway": "Learning without morphology labels supports clustering and merger-candidate review, not automatic physical validation.",
      "issueDate": "2024-05",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "decision-ai",
      "title": "Bom et al. · decision-aware time-domain AI",
      "url": "https://arxiv.org/abs/2606.05285",
      "year": "2026",
      "submitted": "2026-06-03",
      "version": "v1",
      "status": "Submitted Perspective; proposed framework",
      "evidenceType": "Conceptual agenda, not deployed performance",
      "takeaway": "Evaluate follow-up by scientific value, uncertainty and resource constraints under human supervision.",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    },
    {
      "id": "desc-ai",
      "title": "LSST DESC · opportunities in AI/ML",
      "url": "https://arxiv.org/abs/2601.14235",
      "year": "2026",
      "submitted": "2026-01-20",
      "version": "v1.0",
      "status": "Collaboration white paper; not planned for journal submission",
      "evidenceType": "Application survey and research agenda",
      "takeaway": "Photometric redshifts, lensing and simulations share uncertainty and domain-shift challenges.",
      "checked": "2026-09-28",
      "accessed": "2026-09-28"
    }
  ],
  "glossary": [
    {
      "term": "Flux",
      "meaning": "Measured brightness; relative flux divides by a reference baseline.",
      "lesson": "light"
    },
    {
      "term": "ppm",
      "meaning": "Parts per million: fractional depth multiplied by 1,000,000.",
      "lesson": "light"
    },
    {
      "term": "Ephemeris",
      "meaning": "A time prediction specified by a reference epoch, period and time convention.",
      "lesson": "orbits"
    },
    {
      "term": "Cadence",
      "meaning": "Sampling interval; read the actual product metadata and exposure duration.",
      "lesson": "missions"
    },
    {
      "term": "Dilution",
      "meaning": "Extra light reduces the measured fractional depth of an eclipse on a source.",
      "lesson": "impostors"
    },
    {
      "term": "Tensor",
      "meaning": "A numerical array with one or more dimensions, often used for model computation.",
      "lesson": "arrays"
    },
    {
      "term": "Detrending",
      "meaning": "Estimating and removing background variability while attempting to preserve the desired signal.",
      "lesson": "clean"
    },
    {
      "term": "Phase",
      "meaning": "Position within a repeating cycle, commonly between zero and one.",
      "lesson": "fold"
    },
    {
      "term": "BLS",
      "meaning": "Box Least Squares: a search over repeating box-shaped flux decreases.",
      "lesson": "fold"
    },
    {
      "term": "TLS",
      "meaning": "Transit Least Squares: search using more realistic transit-shaped templates.",
      "lesson": "aliases"
    },
    {
      "term": "Alias",
      "meaning": "An alternative period consistent with sampling or repeated event structure.",
      "lesson": "aliases"
    },
    {
      "term": "Likelihood",
      "meaning": "Data compatibility under specified model parameters or hypotheses.",
      "lesson": "noise"
    },
    {
      "term": "Precision",
      "meaning": "TP/(TP+FP): the fraction of selected cases that are labeled positives.",
      "lesson": "metrics"
    },
    {
      "term": "Recall",
      "meaning": "TP/(TP+FN): the fraction of labeled positives that are selected.",
      "lesson": "metrics"
    },
    {
      "term": "AP",
      "meaning": "Average precision: a ranking summary over recall increments for a stated label/population.",
      "lesson": "metrics"
    },
    {
      "term": "Leakage",
      "meaning": "Information crosses an evaluation boundary and makes a result overly optimistic.",
      "lesson": "splits"
    },
    {
      "term": "Calibration",
      "meaning": "Agreement between predicted confidence and observed frequencies in a defined population.",
      "lesson": "probability"
    },
    {
      "term": "Logit",
      "meaning": "The raw binary score before sigmoid; sigmoid(z)=1/(1+exp(−z)).",
      "lesson": "neurons"
    },
    {
      "term": "Parameter",
      "meaning": "A model quantity such as a weight or bias adjusted during fitting.",
      "lesson": "neurons"
    },
    {
      "term": "Hyperparameter",
      "meaning": "A setting such as learning rate or layer width chosen outside the usual weight update.",
      "lesson": "neurons"
    },
    {
      "term": "Loss",
      "meaning": "A numerical objective measuring prediction error under the supplied task.",
      "lesson": "gradients"
    },
    {
      "term": "Gradient",
      "meaning": "Derivatives showing the local sensitivity of loss to parameters.",
      "lesson": "gradients"
    },
    {
      "term": "Backpropagation",
      "meaning": "Efficient chain-rule calculation of gradients through a computation graph.",
      "lesson": "gradients"
    },
    {
      "term": "Learning rate",
      "meaning": "The scale of an optimizer update; too large can overshoot and too small can stall progress.",
      "lesson": "gradients"
    },
    {
      "term": "Batch",
      "meaning": "Examples used together to estimate a training gradient.",
      "lesson": "training"
    },
    {
      "term": "Epoch",
      "meaning": "One dataset pass under the stated sampling convention.",
      "lesson": "training"
    },
    {
      "term": "Overfitting",
      "meaning": "Learning training-specific structure that does not generalize well.",
      "lesson": "training"
    },
    {
      "term": "Seed",
      "meaning": "An initialization for a pseudo-random generator, not a planet probability or a magic model setting.",
      "lesson": "seeds"
    },
    {
      "term": "CNN",
      "meaning": "A neural network using shared local filters across a sequence or image.",
      "lesson": "cnn"
    },
    {
      "term": "Receptive field",
      "meaning": "The region of input that can affect a particular representation.",
      "lesson": "cnn"
    },
    {
      "term": "Gradient boosting",
      "meaning": "A sequential combination of weak models optimized to improve a loss.",
      "lesson": "alternatives"
    },
    {
      "term": "Attention",
      "meaning": "A learned, content-dependent weighted combination of value representations.",
      "lesson": "attention"
    },
    {
      "term": "Transformer",
      "meaning": "An architecture using attention and associated layers to transform token representations.",
      "lesson": "attention"
    },
    {
      "term": "Self-supervision",
      "meaning": "Training with targets constructed from data, such as masked-sample reconstruction.",
      "lesson": "representation"
    },
    {
      "term": "Fine-tuning",
      "meaning": "Updating pretrained weights using a new task or domain’s training data.",
      "lesson": "transfer"
    },
    {
      "term": "DANN",
      "meaning": "Domain-adversarial training: task learning combined with reversed domain gradients to shared features.",
      "lesson": "dann"
    },
    {
      "term": "Gradient reversal",
      "meaning": "Identity on the forward pass; negated and scaled domain gradient on the backward pass.",
      "lesson": "dann"
    },
    {
      "term": "OOD",
      "meaning": "Out-of-distribution: unusual relative to a specified reference population.",
      "lesson": "uncertainty"
    },
    {
      "term": "Ensemble",
      "meaning": "A combination of predictions from several models, which can still share bias.",
      "lesson": "uncertainty"
    },
    {
      "term": "Conformal coverage",
      "meaning": "A prediction-set/interval coverage property under stated assumptions; not an individual planet probability.",
      "lesson": "uncertainty"
    },
    {
      "term": "Difference image",
      "meaning": "A comparison of in-event and out-of-event pixels used to locate changing light.",
      "lesson": "pixels"
    },
    {
      "term": "Validation",
      "meaning": "Evaluation of a planet interpretation against modeled false-positive alternatives under stated assumptions.",
      "lesson": "validation"
    },
    {
      "term": "Checkpoint",
      "meaning": "A saved model state that must be paired with matching architecture and preprocessing.",
      "lesson": "contract"
    },
    {
      "term": "Inference",
      "meaning": "Using fitted parameters to predict; it does not normally update those parameters.",
      "lesson": "operations"
    },
    {
      "term": "Completeness",
      "meaning": "The fraction of relevant signals recovered under a stated search and selection procedure.",
      "lesson": "injections"
    },
    {
      "term": "Ablation",
      "meaning": "A controlled component change used to investigate its contribution.",
      "lesson": "ablation"
    },
    {
      "term": "Falsifiable hypothesis",
      "meaning": "A claim with a specified observation or result that could show it wrong.",
      "lesson": "papers"
    }
  ],
  "project": {
    "checked": "2026-09-28",
    "metric_policy": {
      "classification": "Compare methods only within a named cohort. AP and ROC AUC describe ranking; accuracy uses threshold 0.5. Brier/NLL depend on calibration. None is a blind planet-confirmation probability.",
      "detector": "Incremental one-to-one matched injected events, removing original-curve matches. Host denominator remains all registered hosts; event denominator is the protocol retained injected-event count. Control rate = inverted alerts / summed exposure_days * 27.",
      "uncertainty": "Small fresh samples and reused audits do not establish universal superiority. Paired p-values are unadjusted. Model seed SD is not a confidence interval for planet probability."
    },
    "deployment": {
      "model_name": "frozen_Kepler_shared_v1_CNN_seed42",
      "class": "scripts.research.scoring.FrozenScorer",
      "authoritative_evidence_kind": "model_score",
      "checkpoint_path": "outputs/shared_cnn/kepler/dataset_kepler_shared_v1_cnn_20260915_080811/best_model.pt",
      "checkpoint_sha256": "7890efd17fc072efb74465a9fbfa6fb8b0192388d91af520961349f0066ba703",
      "normalizer_path": "data/processed/kepler/shared_v1/kepler_train_normalization.npz",
      "normalizer_sha256": "6f4ac773f6f2dd6c2200e68b903acb0c7a3f585a593ac2d882c03af03c705dc1",
      "input_contract": {
        "name": "shared_v1",
        "global_bins": 200,
        "local_bins": 100,
        "scalar_features": 7,
        "flat_features": 907,
        "normalization": "frozen Kepler TRAIN moments"
      },
      "semantics": "sigmoid_ranking_score_not_planet_confirmation_probability",
      "calibration": "not_calibrated_for_blind_search",
      "source_validation_threshold": 0.7849999999999999,
      "threshold_use": "recorded_source_validation_F1_only_not_a_search_gate",
      "limits": [
        "Records prove completed scoring on 2026-09-26, not a new scoring event on 2026-09-28.",
        "Experimental comparison scores are appended separately and do not replace authoritative model_score.",
        "No deployed Transformer, nonlinear stack, neural localizer v3 or recovery hybrid is established by these records."
      ],
      "latest_completed_score_at": "2026-09-26T22:54:24.879009Z"
    },
    "watcher": {
      "as_of_utc": "2026-09-28T13:57:36.139457+00:00",
      "selected_target_count": 18,
      "scope": "bounded_sample_of_public_TESS_SPOC_observations",
      "archive_wide_complete": false,
      "exhausted_reason": "target_selection_full",
      "correction": "Two fixed control stars describe the September 23 historical setup. Current schema-2 archival_pilot discovers a bounded sample, capped at 18 selected targets, with two products per cycle and a six-hour configured interval. Selection full does not mean the whole archive has been searched.",
      "schema_version": 2,
      "cohort": "archival_pilot",
      "poll_seconds": 21600,
      "max_products_per_cycle": 2
    },
    "historical_dann": {
      "source": "results/mission_adaptation_pilot/summary.json",
      "generated_at": "2026-09-23T16:02:43.503039Z",
      "audit_rows": 82,
      "audit_host_groups": 79,
      "seeds": [
        42,
        43,
        44
      ],
      "updates_per_fit": 120,
      "fits": 15,
      "methods": {
        "dann": {
          "mean": 0.6933715821549344,
          "sd": 0.00027602448669550143,
          "values": [
            0.693401393985691,
            0.6936314906465944,
            0.6930818618325181
          ]
        },
        "fine_tuned": {
          "mean": 0.7644444642874241,
          "sd": 0.01795150409809908,
          "values": [
            0.7465778541315504,
            0.7824796746899395,
            0.7642758640407821
          ]
        },
        "kepler_only": {
          "mean": 0.5587534468305261,
          "sd": 0.03147136678270309,
          "values": [
            0.5837345714469147,
            0.5234067149647096,
            0.569119054079954
          ]
        },
        "pooled": {
          "mean": 0.7067378374650864,
          "sd": 0.012438511854217887,
          "values": [
            0.7167731835738648,
            0.7106187850063452,
            0.6928215438150493
          ]
        },
        "tess_only": {
          "mean": 0.7473523036732489,
          "sd": 0.013121909794847605,
          "values": [
            0.7327392337031513,
            0.7511906754267164,
            0.7581270018898789
          ]
        }
      },
      "comparison_inference": {
        "saved_proposals": 44,
        "real_known_object_controls": 17,
        "synthetic_or_transformed_controls": 27,
        "date": "2026-09-23"
      },
      "limits": [
        "Known catalog ephemerides; not blind recovery",
        "Short budgets; no convergence claim",
        "Validation-derived audit; previously consulted benchmark is not an untouched test",
        "TESS-only weights share frozen Kepler TRAIN normalization",
        "Kepler-only selects and calibrates on Kepler; other arms on TESS",
        "Empirical labelled-negative FPR is not survey false-alarm calibration",
        "DANN uses both missions' labels; no unsupervised-adaptation claim",
        "Mission head accuracy alone does not prove invariant representations",
        "Calibrated scores are not planet confirmation probabilities"
      ],
      "decision": "Historical short-budget fine-tuning has highest mean AP; DANN benefit was not demonstrated. Fresh Kepler-only arm is not the older deployed frozen CNN. Retain as historical evidence, not current full leaderboard."
    },
    "reused_classifier": {
      "source": "results/crossfit_supermodel_v2/summary.json",
      "generated_at": "2026-09-28T05:10:47.813175Z",
      "audit_rows": 82,
      "positive": 44,
      "negative": 38,
      "partitions_rows": {
        "audit": 82,
        "calibration": 81,
        "selection": 162,
        "train": 538
      },
      "experts": [
        "tess_only",
        "kepler_only",
        "fine_tuned",
        "pooled",
        "dann",
        "transformer",
        "transit_morphology",
        "stellar_variability",
        "tls",
        "aperture_photometry",
        "difference_image"
      ],
      "selected_configuration": {
        "blend": 0.5,
        "l2_regularization": 10.0,
        "max_leaf_nodes": 7,
        "selection_average_precision": 0.8818776174128418,
        "selection_brier": 0.1502933668257696,
        "selection_nll": 0.4736246565941875
      },
      "limits": [
        "The audit is validation-derived and was consulted by earlier experiments",
        "Selection labels choose tree complexity, regularization and blend strength",
        "Physical experts use known catalog ephemerides on these labelled examples",
        "A new frozen host-disjoint evaluation is required for a paper-level claim"
      ],
      "decision": "Nonlinear eleven-expert stack leads these AP/AUC comparisons on a reused development/audit cohort. This is not independent confirmation or deployment justification.",
      "methods": {
        "crossfit_nonlinear": {
          "average_precision": 0.8716273788620068,
          "roc_auc": 0.832535885167464,
          "n": 82
        },
        "stellar_variability": {
          "average_precision": 0.8630833445673054,
          "roc_auc": 0.819377990430622,
          "n": 82
        },
        "v4_static_stack": {
          "average_precision": 0.8613152514966733,
          "roc_auc": 0.8086124401913876,
          "n": 82
        }
      }
    },
    "fresh_classifier": {
      "source": "outputs/research/fresh_classifier_audit/audit-v1/summary.json",
      "completed_at": "2026-09-28T13:27:30.382396Z",
      "registered_candidates": 295,
      "accepted_candidates": 14,
      "positive": 3,
      "negative": 11,
      "acquisition": {
        "source": "outputs/research/fresh_classifier_audit/audit-v1/preparation.json",
        "json_pointer": "/audit",
        "statuses": {
          "rejected": 281,
          "accepted": 14
        },
        "rejection_reasons": {
          "no_public_120s_product": 281
        },
        "available_passed_unchanged_preparation": 14,
        "registered_coverage_fraction": 0.04745762711864407
      },
      "calibration_caveat": "Supermodel Brier/NLL use frozen temperature 0.836210480795994; comparator Brier/NLL use raw logits. AP/AUC rank logits. Do not call this a matched-calibration superiority result.",
      "limits": [
        "Archive availability and unchanged coverage rules restrict this cohort.",
        "A small, imbalanced audit cannot establish a general superiority claim.",
        "Labels are catalog dispositions from a pinned snapshot, not independent follow-up.",
        "Latest three LC sectors and one pixel sector per host; known ephemerides."
      ],
      "claims": {
        "deployed": false,
        "large_confirmatory_audit": false,
        "new_host_validation": true,
        "weights_or_thresholds_tuned": false
      },
      "decision": "Static v4 ranks all 3 positives above 11 negatives (AP/AUC 1); nonlinear has 13/14 correct versus 12/14 for v4 at 0.5. Ranking and threshold accuracy answer different questions; cohort is too small and coverage-selected for a general winner.",
      "methods": {
        "crossfit_supermodel": {
          "average_precision": 0.8333333333333333,
          "roc_auc": 0.9090909090909091,
          "brier": 0.10674314753925308,
          "n": 14,
          "correct_at_0_5": 13,
          "at_0_5": {
            "fn": 1,
            "fp": 0,
            "fpr": 0.0,
            "precision": 1.0,
            "recall": 0.6666666666666666,
            "selected": 2,
            "threshold": 0.5,
            "tn": 11,
            "tp": 2
          },
          "calibration": "Frozen temperature 0.836210480795994"
        },
        "v4_static": {
          "average_precision": 1.0,
          "roc_auc": 1.0,
          "brier": 0.1351477895434869,
          "n": 14,
          "correct_at_0_5": 12,
          "at_0_5": {
            "fn": 2,
            "fp": 0,
            "fpr": 0.0,
            "precision": 1.0,
            "recall": 0.3333333333333333,
            "selected": 1,
            "threshold": 0.5,
            "tn": 11,
            "tp": 1
          },
          "calibration": "Raw logits (no matched temperature fit)"
        }
      }
    },
    "physical_benchmark": {
      "source": "outputs/research/ai_telescope/physical-benchmark-v1/summary.json",
      "completed_at": "2026-09-28T12:53:26.563870Z",
      "registered_hosts": 90,
      "observable_hosts": 85,
      "injected_events": 330,
      "calibration_hosts": 78,
      "limits": [
        "Physical limb-darkened circular transit model with synthetic stellar density, fixed limb darkening and empirical static PSF; not real planet discoveries.",
        "One sector per host; no established background-source rejection, eclipsing-binary rejection or multi-sector sensitivity.",
        "Inverted-control alerts per exposure are not a survey astrophysical false-positive rate.",
        "Event matching within half true duration is not necessarily correct orbital-period recovery, especially for single-transit TLS matches.",
        "Read sensitivity and control burden together; no universal winner across classifier and detector tasks."
      ],
      "claims": {
        "model_training_or_tuning_on_evaluation": false,
        "planet_classification": false,
        "survey_false_positive_rate": false,
        "watcher_deployed": false
      },
      "decision": "Original physical audit: v3 fails the budget of 1 control alert/27 exposure-days; v3-v2 host recovery difference not conclusive (paired exact p=0.21875). TLS equals v3 host count and has more event recoveries.",
      "methods": {
        "bls": {
          "incremental_hosts": 1,
          "incremental_events": 1,
          "inverted_alerts": 0,
          "inverted_alerts_per_27_days": 0.0,
          "control_exposure_days_recomputed": 2070.8886979429517
        },
        "tls": {
          "incremental_hosts": 17,
          "incremental_events": 88,
          "inverted_alerts": 45,
          "inverted_alerts_per_27_days": 0.5867046361336945,
          "control_exposure_days_recomputed": 2070.8886979429517
        },
        "v2": {
          "incremental_hosts": 13,
          "incremental_events": 34,
          "inverted_alerts": 69,
          "inverted_alerts_per_27_days": 0.8996137754049984,
          "control_exposure_days_recomputed": 2070.8886979429517
        },
        "v3": {
          "incremental_hosts": 17,
          "incremental_events": 44,
          "inverted_alerts": 105,
          "inverted_alerts_per_27_days": 1.368977484311954,
          "control_exposure_days_recomputed": 2070.8886979429517
        }
      },
      "thresholds": {
        "bls": 100.0,
        "tls": 8.0,
        "v2": 0.9,
        "v3": 0.86
      },
      "v3_v2_paired_p": 0.21875
    },
    "fresh_recovery": {
      "source": "outputs/research/ai_telescope/recovery-v1/summary.json",
      "completed_at": "2026-09-28T13:37:52.250186Z",
      "registered_hosts": 99,
      "observable_hosts": 96,
      "injected_events": 326,
      "calibration_hosts": 78,
      "limits": [
        "Physical limb-darkened circular transit model with synthetic stellar density, fixed limb darkening and empirical static PSF; not real planet discoveries.",
        "One sector per host; no established background-source rejection, eclipsing-binary rejection or multi-sector sensitivity.",
        "Inverted-control alerts per exposure are not a survey astrophysical false-positive rate.",
        "Event matching within half true duration is not necessarily correct orbital-period recovery, especially for single-transit TLS matches.",
        "Read sensitivity and control burden together; no universal winner across classifier and detector tasks."
      ],
      "claims": {
        "classifier_validation": false,
        "deployed": false,
        "fresh_host_evaluation": true,
        "hybrid_within_control_budget": true
      },
      "decision": "Recovery changes search and thresholds, not neural weights. Hybrid rejected. All methods miss all 25 registered 500-ppm injections; v3 single-transit 4/33, TLS 3/33 incidental event matches, not recovered single-transit periods.",
      "methods": {
        "bls_exact": {
          "incremental_hosts": 0,
          "incremental_events": 0,
          "inverted_alerts": 0,
          "inverted_alerts_per_27_days": 0.0,
          "control_exposure_days_recomputed": 2199.044553302694
        },
        "hybrid": {
          "incremental_hosts": 5,
          "incremental_events": 17,
          "inverted_alerts": 33,
          "inverted_alerts_per_27_days": 0.4051759654718354,
          "control_exposure_days_recomputed": 2199.044553302694
        },
        "single_event": {
          "incremental_hosts": 2,
          "incremental_events": 4,
          "inverted_alerts": 34,
          "inverted_alerts_per_27_days": 0.41745402503158796,
          "control_exposure_days_recomputed": 2199.044553302694
        },
        "tls_exact": {
          "incremental_hosts": 22,
          "incremental_events": 105,
          "inverted_alerts": 32,
          "inverted_alerts_per_27_days": 0.3928979059120828,
          "control_exposure_days_recomputed": 2199.044553302694
        },
        "v3_calibrated": {
          "incremental_hosts": 21,
          "incremental_events": 53,
          "inverted_alerts": 14,
          "inverted_alerts_per_27_days": 0.17189283383653622,
          "control_exposure_days_recomputed": 2199.044553302694
        },
        "v3_original": {
          "incremental_hosts": 21,
          "incremental_events": 58,
          "inverted_alerts": 27,
          "inverted_alerts_per_27_days": 0.33150760811331986,
          "control_exposure_days_recomputed": 2199.044553302694
        }
      },
      "derived_comparison": {
        "inverted_control_relative_reduction": 0.4814814814814815,
        "formula": "1 - (14/27); both methods have the same summed control exposure",
        "host_count_change": 0,
        "event_count_change": -5,
        "both_v3_mean_control_rates_below_budget_1": true,
        "same_host_count_not_identical_hosts": true,
        "calibrated_only_hosts": 1,
        "original_only_hosts": 1
      },
      "by_depth": {
        "0.0005": {
          "bls_exact": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "hybrid": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "single_event": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "tls_exact": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "v3_calibrated": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "v3_original": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          }
        },
        "0.001": {
          "bls_exact": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "hybrid": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "single_event": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "tls_exact": {
            "registered_hosts": 25,
            "incremental_hosts": 6
          },
          "v3_calibrated": {
            "registered_hosts": 25,
            "incremental_hosts": 4
          },
          "v3_original": {
            "registered_hosts": 25,
            "incremental_hosts": 3
          }
        },
        "0.002": {
          "bls_exact": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "hybrid": {
            "registered_hosts": 25,
            "incremental_hosts": 1
          },
          "single_event": {
            "registered_hosts": 25,
            "incremental_hosts": 0
          },
          "tls_exact": {
            "registered_hosts": 25,
            "incremental_hosts": 5
          },
          "v3_calibrated": {
            "registered_hosts": 25,
            "incremental_hosts": 5
          },
          "v3_original": {
            "registered_hosts": 25,
            "incremental_hosts": 5
          }
        },
        "0.005": {
          "bls_exact": {
            "registered_hosts": 24,
            "incremental_hosts": 0
          },
          "hybrid": {
            "registered_hosts": 24,
            "incremental_hosts": 4
          },
          "single_event": {
            "registered_hosts": 24,
            "incremental_hosts": 2
          },
          "tls_exact": {
            "registered_hosts": 24,
            "incremental_hosts": 11
          },
          "v3_calibrated": {
            "registered_hosts": 24,
            "incremental_hosts": 12
          },
          "v3_original": {
            "registered_hosts": 24,
            "incremental_hosts": 13
          }
        }
      },
      "by_mode": {
        "periodic": {
          "bls_exact": {
            "registered_hosts": 33,
            "incremental_hosts": 0
          },
          "hybrid": {
            "registered_hosts": 33,
            "incremental_hosts": 2
          },
          "single_event": {
            "registered_hosts": 33,
            "incremental_hosts": 1
          },
          "tls_exact": {
            "registered_hosts": 33,
            "incremental_hosts": 12
          },
          "v3_calibrated": {
            "registered_hosts": 33,
            "incremental_hosts": 8
          },
          "v3_original": {
            "registered_hosts": 33,
            "incremental_hosts": 7
          }
        },
        "single": {
          "bls_exact": {
            "registered_hosts": 33,
            "incremental_hosts": 0
          },
          "hybrid": {
            "registered_hosts": 33,
            "incremental_hosts": 1
          },
          "single_event": {
            "registered_hosts": 33,
            "incremental_hosts": 1
          },
          "tls_exact": {
            "registered_hosts": 33,
            "incremental_hosts": 3
          },
          "v3_calibrated": {
            "registered_hosts": 33,
            "incremental_hosts": 4
          },
          "v3_original": {
            "registered_hosts": 33,
            "incremental_hosts": 4
          }
        },
        "ttv": {
          "bls_exact": {
            "registered_hosts": 33,
            "incremental_hosts": 0
          },
          "hybrid": {
            "registered_hosts": 33,
            "incremental_hosts": 2
          },
          "single_event": {
            "registered_hosts": 33,
            "incremental_hosts": 0
          },
          "tls_exact": {
            "registered_hosts": 33,
            "incremental_hosts": 7
          },
          "v3_calibrated": {
            "registered_hosts": 33,
            "incremental_hosts": 9
          },
          "v3_original": {
            "registered_hosts": 33,
            "incremental_hosts": 10
          }
        }
      },
      "thresholds": {
        "bls_exact": 231.95611061593218,
        "hybrid_neural": 0.985,
        "hybrid_single": 34.468068817779766,
        "single_event": 32.73197682404179,
        "tls_exact": 9.663561072185,
        "v3_calibrated": 0.9,
        "v3_original": 0.86
      }
    },
    "continuous_history": {
      "source": "results/ai_telescope_continuous_v3/README.md",
      "cohort": "reused 79-host trapezoidal audit, 276 events; not the later physical benchmark",
      "v2": {
        "threshold": 0.9,
        "hosts": 21,
        "events": 41,
        "control_rate_rounded": 0.745
      },
      "v3": {
        "threshold": 0.86,
        "hosts": 28,
        "events": 53,
        "control_rate_rounded": 0.517
      },
      "paired_exact_p_rounded": 0.092,
      "limits": "Historical exploratory improvement. Do not compare percentages directly with stricter physical injection and one-to-one matching protocol. Later physical and fresh tests now exist; earlier README future-work lists are historical."
    },
    "rejected_routing": {
      "behavioral_v4": {
        "source": "results/behavioral_supermodel_v4/report.md",
        "status": "did not beat strongest single expert on both declared audit metrics"
      },
      "diagnostic_v5": {
        "source": "results/behavioral_supermodel_v5/report.md",
        "status": "dynamic gate selected but did not beat static stack and strongest single expert on both declared metrics"
      },
      "crossfit_competence": {
        "source": "results/crossfit_competence_v1/report.md",
        "routing_strength": 0.0,
        "status": "selection returned the static prior; not a successful adaptive router"
      }
    },
    "baseline_calibration_resolution": {
      "bls": {
        "events_per_27_days": 0.9206593202856168,
        "exact_empirical_threshold": 72.59677975066101,
        "original_coarse_threshold": 100.0,
        "scope": "calibration-only grid-resolution diagnostic; not an evaluated operating point"
      },
      "tls": {
        "events_per_27_days": 0.9810304232551653,
        "exact_empirical_threshold": 7.5604120902904,
        "original_coarse_threshold": 8.0,
        "scope": "calibration-only grid-resolution diagnostic; not an evaluated operating point"
      }
    },
    "baseline_calibration_resolution_note": "Calibration-only exact old-budget boundaries were not evaluated by rescoring fresh/historical hosts. Exact score boundaries resolve grid mechanics, not low sensitivity from a conservative transfer margin.",
    "reports": [
      [
        "Historical adaptation pilot",
        "results/mission_adaptation_pilot/README.md"
      ],
      [
        "Reused classifier audit",
        "results/crossfit_supermodel_v2/report.md"
      ],
      [
        "Fresh classifier audit",
        "results/fresh_classifier_audit_v1/README.md"
      ],
      [
        "Continuous v2 validation",
        "results/ai_telescope_continuous_validation_v1/README.md"
      ],
      [
        "Continuous v3 history",
        "results/ai_telescope_continuous_v3/README.md"
      ],
      [
        "Original physical benchmark",
        "results/ai_telescope_physical_benchmark_v1/README.md"
      ],
      [
        "Fresh recovery study",
        "results/ai_telescope_recovery_v1/README.md"
      ],
      [
        "Consolidated limitations",
        "results/research_fixes_v1/README.md"
      ]
    ],
    "stages": [
      [
        "Archive products",
        "18 selected archival targets in the 28 September snapshot; six-hour polling and two products per cycle.",
        "operations"
      ],
      [
        "Clean and detect",
        "Watcher BLS proposals; offline localizer and physical-injection studies remain research-only.",
        "fold"
      ],
      [
        "Build model inputs",
        "shared_v1 global/local arrays + seven scalars; frozen Kepler training normalization.",
        "contract"
      ],
      [
        "Rank and compare",
        "Frozen Kepler CNN stays authoritative; appended comparison evidence does not replace it.",
        "results"
      ],
      [
        "Check and review",
        "Inspect aliases, source location and catalog context; model rank does not validate a planet.",
        "vetter"
      ],
      [
        "Preserve and investigate",
        "Keep dated results, live dossiers and proposed experiments distinct.",
        "reproduce"
      ]
    ]
  }
};
