# Run Folder Design

The run folder needs to be instantiated once at the start of the program. The contents of the folder will be as follows:

```text
./outputs/run_<timestamp>/
├── researchers/
│   ├── researcher_1/
│   │   ├── validator/
|   |   |    ├── summary.md
|   |   |    └── validation_criteria.json
│   │   ├── summary.md
│   │   ├── tasking.md
│   ├── researcher_2/
│   ├── .../
│   └── researcher_n/
├── pdfs/
├── synthesis/
└── planner_manifest.json
```
