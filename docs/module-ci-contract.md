# TinyHumans module CI contract

Module repositories call the reusable workflow at
`.github/workflows/module-ci.yml` in `tinyhumansai/.github`. The workflow
publishes the same required check names in every caller:

- `fmt`
- `clippy`
- `test`
- `coverage`
- `docs`
- `msrv`
- `supply-chain`
- `module-e2e (ubuntu-latest)`, `module-e2e (macos-latest)`,
  `module-e2e (windows-latest)`
- `feature-tests (ubuntu-latest)`, `feature-tests (macos-latest)`,
  `feature-tests (windows-latest)`

Each module owns its test commands and platform dependencies. The workflow
caller supplies the module's coverage command, declared MSRV, module loader
suite, feature suite, and any Ubuntu packages needed to build or test it. A
caller is ready to become a required-check ruleset target only after every
supplied command succeeds on its target runners.

Do not rename or remove a required job in the shared workflow without updating
the organization ruleset and the drift check in OpenHuman in the same change.
