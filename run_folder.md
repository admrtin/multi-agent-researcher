# Run Folder Design

The run folder is instantiated once per planner run. The contents of the folder will be as follows:

```text
./outputs/run_<timestamp>/
├── planner_manifest.json
├── papers/
│   ├── <paper_1>.pdf
│   ├── <paper_2>.pdf
│   └── ...
├── researchers/
│   ├── researcher_1/
│   │   ├── tasking.md
│   │   ├── summary.md
│   │   └── validator/
│   │       ├── validation_criteria.json
│   │       └── validation_summary.md
│   ├── researcher_2/
│   │   ├── tasking.md
│   │   ├── summary.md
│   │   └── validator/
│   │       ├── validation_criteria.json
│   │       └── validation_summary.md
│   ├── ...
│   └── researcher_n/
│       ├── tasking.md
│       ├── summary.md
│       └── validator/
│           ├── validation_criteria.json
│           └── validation_summary.md
└── synthesis/
    ├── synthesis_report.md
    └── synthesis_summary.json
```