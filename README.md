# 🏈 Fantasy Football Oracle

The Fantasy Football Oracle is an advanced, conversational AI chatbot designed to answer questions about a fantasy football league's history by querying a SQL database. It features a sophisticated, multi-step architecture that ensures both accuracy and performance, making it a robust and reliable data analyst.

## Table of Contents
- [Features](#features)
- [Core Architecture](#core-architecture)
- [How It Works: A Step-by-Step Example](#how-it-works-a-step-by-step-example)
- [Technical Stack](#technical-stack)
- [Setup and Installation](#setup-and-installation)
- [Project Structure](#project-structure)
- [Logging and Debugging](#logging-and-debugging)

## Features
- **Natural Language Queries:** Ask complex questions in plain English (e.g., "who had the most passing yards in 2019?" or "what was my win/loss record against Jake?").
- **Conversational Context:** The chatbot remembers previous turns in the conversation, allowing for follow-up questions (e.g., "who won the league in 2018?" followed by "what was their team name?").
- **Performant and Responsive:** Utilizes caching to ensure fast responses after the initial startup.
- **Accurate and Constrained:** Employs a multi-step agentic workflow to prevent errors and ensure queries are based on a rich, accurate understanding of the database schema.
- **Detailed In-App Debugging:** An "Agent's Internal Context" expander shows exactly what information the AI is using to answer your question, providing full transparency.

## Core Architecture
This application's strength lies in its **two-stage, "Constrained Agent" architecture**. Instead of giving a powerful AI agent free rein over the entire database (which is slow and error-prone), we break the problem into two distinct steps:

```mermaid
graph TD
    A[User Input: "Who won in 2018?"] --> B{Stage 1: Table Selector};
    B --> C[Identifies Tables: <br/>- FantasySeasons_LLM<br/>- FantasyOwners_LLM];
    C --> D{Stage 2: Constrained Agent};
    D --> E[Receives Detailed Schema <br/>for ONLY selected tables];
    E --> F{Executes JOIN Query <br/>on Database};
    F --> G[Final Answer: "Jake"];

    subgraph "Context Provided"
        H[table_dictionary.csv] --> B;
        I[data_dictionary.csv] --> D;
        J[Database] --> F;
    end

    style A fill:#D0E8FF,stroke:#333,stroke-width:2px
    style G fill:#D5F5E3,stroke:#333,stroke-width:2px

### Stage 1: The Database Router (Table Selector)

This is a lightweight, specialized LLM call whose only job is to act as a "database router."

1.  **Input:** The user's question, the conversation history, and a high-level dictionary of all available tables (`table_dictionary.csv`).
2.  **Task:** To analyze the user's intent and identify the **minimal set of tables** required to answer the question. It's prompted to think deeply about the query, understanding that a question like "who won?" requires both a "seasons" table and an "owners" table.
3.  **Output:** A simple, comma-separated list of required table names (e.g., `FantasySeasons_LLM,FantasyOwners_LLM`).

This pre-filtering step is crucial for both performance and accuracy. It prevents the final agent from being overwhelmed with dozens of irrelevant table schemas.

### Stage 2: The Constrained SQL Agent

This is the main "worker" agent, but it operates under strict constraints based on the output from Stage 1.

1.  **Dynamic Context:** The agent is initialized *dynamically* for each query. It is only given the detailed, human-readable schema for the tables selected in Stage 1. This schema is loaded from our rich `data_dictionary.csv`, which provides crucial semantic context (e.g., explaining that `season_id` represents the year).
2.  **Methodical Reasoning:** The agent is prompted to be methodical, taking one small step at a time and not predicting results. It uses the **ReAct (Reasoning and Acting)** framework to formulate a thought, choose an action (e.g., `sql_db_query`), run it, and observe the result before deciding on its next thought.
3.  **Self-Correction:** The agent is explicitly instructed on how to handle errors. If it generates a faulty SQL query, it analyzes the database error message and attempts to correct the query, making the system highly resilient.

This architecture ensures the final agent is focused, efficient, and working with the richest possible context for the specific task at hand.

## How It Works: A Step-by-Step Example

**User:** "Who won the championship in 2018?"

1.  **Simple Router:** The app first checks if it's a simple greeting. It is not.
2.  **Table Selector (Stage 1):**
    - The selector LLM receives the question and table descriptions.
    - It reasons: "'who' implies a person's name, so I need the `FantasyOwners_LLM` table. 'championship in 2018' implies I need the `FantasySeasons_LLM` table."
    - It returns the list: `['FantasySeasons_LLM', 'FantasyOwners_LLM']`.
3.  **Schema Injection:**
    - The application reads `data_dictionary.csv` and builds a detailed, human-readable schema string containing column descriptions for *only* those two tables.
4.  **Constrained Agent (Stage 2):**
    - A new agent is created and given the detailed schema.
    - **Thought 1:** "I need to find the winner's name. I can get the `champion_owner_id` from `FantasySeasons_LLM` where `season_id` is 2018, and then use that ID to find the name in `FantasyOwners_LLM`. A `JOIN` would be efficient."
    - **Action:** `sql_db_query` with input `SELECT T2.owner_name FROM FantasySeasons_LLM AS T1 JOIN FantasyOwners_LLM AS T2 ON T1.champion_owner_id = T2.owner_id WHERE T1.season_id = 2018`.
    - **Observation:** `[('Jake',)]`
    - **Thought 2:** "I have received the result 'Jake'. This answers the user's question."
    - **Final Answer:** `Jake`
5.  **Memory:** The user's question and the AI's final answer are saved to the conversation memory for future context.

## Technical Stack

- **Framework:** [Streamlit](https://streamlit.io/)
- **LLM Orchestration:** [LangChain](https://www.langchain.com/)
- **LLM Provider:** [Google Gemini](https://ai.google.dev/)
- **Database:** SQLite
- **UI:** Streamlit Chat Interface

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/fantasy-chatbot.git
    cd fantasy-chatbot
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Set up your environment variables:**
    - Create a file named `.env` in the root directory.
    - Add your Google API key to this file:
      ```
      GOOGLE_API_KEY="your_api_key_here"
      ```

4.  **Run the application:**
    ```bash
    streamlit run app.py
    ```

## Project Structure

```
.
├── 📄 .env                  # Environment variables (GOOGLE_API_KEY)
├── 📄 README.md              # This file
├── 📄 requirements.txt       # Python dependencies
├── 📄 app.py                # Main Streamlit application and agent logic
├── 📄 llm_fantasy_data.db     # The SQLite database
├── 📄 table_dictionary.csv    # High-level descriptions for the Table Selector
├── 📄 data_dictionary.csv     # Detailed column descriptions for the Agent
└── 📄 agent_debug.log         # Detailed log file for debugging
```

## Logging and Debugging

The application is heavily instrumented for debugging:

- **`agent_debug.log`:** A comprehensive log file that records every step of the agent's reasoning process, including the full context it receives, every action it takes, and every observation it makes.
- **In-App Expander:** The UI contains a collapsible "Agent's Internal Context" box for every query. This provides immediate, real-time insight into which tables were selected and what schema information was provided to the agent, making it easy to diagnose issues without checking log files.#   f a n t a s y - f o o t b a l l - c h a t b o t 
 
 