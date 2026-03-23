# DSCI 576 Multi Agent Researcher Project - Group 6

## Clone the repository: 
`git clone <repo-url>`

`cd multi_agent_researcher`

## Setup Python Environment
`python -m venv .venv`

`pip install --upgrade pip`

## Install Dependencies
Linux/MacOS: `source .venv/bin/activate`          

In Windows: `.venv\Scripts\activate`

`pip install -r requirements.txt`

## API Keys
`cp .env.example .env`

* After executing above, edit .env and fill in your API keys


## Running Google ADK
To start chatting with the root agent, if everything is set up correctly and your CWD is `multi_agent_researcher`, you should be able to run:

`adk run .`


This will instantiate the CLI window for the root agent, which then interfaces with the subagents.