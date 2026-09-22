# Offline MAST replay fixtures

These small **synthetic test records** mirror documented CAOM observations and
products. TIC 123, product sizes, identities and processing versions are fixtures;
they are not actual public-release evidence or a scientific target selection.
Tests use temporary databases and generated, checksummed native FITS photometry.

- `initial`: one public observation and LC.
- `duplicate`: identical rows returned twice; same release/product must be reused.
- `new_release`: an additional sector/build; retain prior immutable records.
- `reprocessed`: changed processing version at the same URI; new product identity.

The tests exercise the same parser/persistence/dispatcher as live MAST, with no
network calls. The HTTP integration uses a local archive fixture and also calls
the actual research HTTP/API, blind detector and (when locally installed) trained
checkpoint. Fixture records are never inserted into the default research store.
