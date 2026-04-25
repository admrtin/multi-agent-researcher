# JSON Architecture

The run folder, defined in `run_folder.md`, is instantiated once per planner run.

The JSON files that need to be created are:

- In the main run folder:
  - `planner_manifest.json`

- In each researcher validator folder:
  - `validation_criteria.json`

- In the synthesis folder:
  - `synthesis_summary.json`

## JSON Format

### `validation_criteria.json`

```json
{
  "researcher_summary_exists": false,
  "researcher_summary_relevant_to_planner_topic": false,
  "researcher_summary_scientifically_grounded": false,
  "researcher_summary_grammatically_correct": false,
  "citations_exist": false,
  "citations_valid": false,
  "citations_relevant_to_summary": false
}
```

The validator agent:

1. Reads the researcher’s `summary.md`.
2. Evaluates the summary against the validation criteria.
3. Saves the results to `validation_criteria.json`.
4. Saves narrative feedback to `validation_summary.md`.

If any value in `validation_criteria.json` is `false`, the researcher loop should revise `summary.md` and run validation again. If all values are `true`, the researcher’s summary is complete and ready for the Synthesizer Agent.

The Synthesizer Agent reads `planner_manifest.json` and each validated researcher `summary.md`, then saves a final structured synthesis to `synthesis_summary.json` and a readable literature review to `synthesis_report.md`.

### `planner_manifest.json`
```json
{
  "planner_topic": "<planner_topic>",
  "timestamp": "<timestamp>",
  "researchers": [
    {
      "id": "researcher_1",
      "title": "<paper_title>",
      "year": "<paper_year>",
      "abstract": "<paper_abstract>",
      "pdf_link": "<paper_pdf_url>",
      "summary": "summary.md"
    },
    {
      "id": "researcher_2",
      "title": "<paper_title>",
      "year": "<paper_year>",
      "abstract": "<paper_abstract>",
      "pdf_link": "<paper_pdf_url>",
      "summary": "summary.md"
    }
  ]
}
```
The planner manifest contains the global information for the run, including the planner topic, timestamp, assigned researcher IDs, paper metadata, PDF links, and expected summary filename.

### `synthesis_summary.json`
```json
{
  "planner_topic": "",
  "timestamp": "",
  "papers_synthesized": [
    {
      "researcher_id": "",
      "title": "",
      "year": "",
      "summary_path": ""
    }
  ],
  "missing_outputs": [],
  "shared_themes": [],
  "key_differences": [],
  "limitations": [],
  "research_gaps": [],
  "future_directions": [],
  "relevance_to_topic": ""
}
```

The Synthesizer Agent reads planner_manifest.json and each validated researcher summary.md, then saves a final structured synthesis to synthesis_summary.json and a readable literature review to synthesis_report.md.