import os
import csv
import logging
import streamlit as st
from dotenv import load_dotenv
from typing import Any, List, Optional, Set, Dict

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import AgentAction, AgentFinish
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool

## Import ConversationBufferMemory for stateful chat history.
from langchain.memory import ConversationBufferMemory

# --- Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="agent_debug.log",
    filemode="w",
)
logger = logging.getLogger(__name__)


class LoggingCallbackHandler(BaseCallbackHandler):
    def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> Any:
        """Log the inputs when a chain starts, with checks for None."""
        # This check prevents the AttributeError
        if serialized is None:
            return

        logger.info("=" * 80)
        # Safely get the name of the chain/component that is starting
        chain_name = serialized.get("name", serialized.get("id", ["UnknownChain"])[-1])
        logger.info(f"CHAIN START: {chain_name}")
        logger.info("INPUTS:")

        for key, value in inputs.items():
            if key == "agent_scratchpad":
                logger.info(f"  - {key}: [present]")
                continue
            # Truncate long history strings for cleaner logs
            if key == "history" and len(str(value)) > 400:
                logger.info(f"  - {key}: [present, truncated]")
                continue
            logger.info(f"  - {key}:\n{value}")
        logger.info("=" * 80)

    def on_agent_action(self, action: AgentAction, **kwargs: Any) -> Any:
        logger.info(
            f"Agent Action: {action.tool} called with input:\n{action.tool_input}"
        )

    def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        logger.info(f"Tool End: Tool produced output:\n{output}")

    def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        logger.info(f"Agent Finished: Final Answer:\n{finish.return_values['output']}")
        logger.info("=" * 80 + "\n")


load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    raise ValueError("GOOGLE_API_KEY not found.")


## Use st.cache_resource to initialize expensive objects like LLMs and DB connections once.
## This prevents re-loading on every user interaction, significantly improving performance.
@st.cache_resource
def get_llm():
    """Initializes and returns the LLM instance."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite-preview-06-17",
        temperature=0,  # Using the latest flash model
    )


@st.cache_resource
def get_db():
    """Initializes and returns the database connection."""
    # Note: Using your provided data_dictionary.csv for more detailed schema info
    # would be a great "next step" for accuracy. For now, this is fine.
    return SQLDatabase.from_uri(
        f"sqlite:///{'llm_fantasy_data.db'}",
        sample_rows_in_table_info=0,  # Set to 0 to not clutter the prompt with sample rows
        lazy_table_reflection=True,
        view_support=True,
    )


llm = get_llm()
db = get_db()


# --- Caching and Helper Functions ---
@st.cache_data
def load_table_descriptions(filepath: str) -> str:
    # (No changes here, this is correct)
    try:
        with open(filepath, mode="r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            return "\n".join(
                [
                    f"Table: {row['table_name']}, Description: {row['table_description']}"
                    for row in reader
                ]
            )
    except Exception as e:
        st.error(f"Failed to load table dictionary: {e}")
        return ""


@st.cache_data
def get_detailed_schema_info(
    table_names: List[str], filepath: str = "data_dictionary.csv"
) -> str:
    """
    Parses the data dictionary to get rich, human-readable column descriptions.
    This version is more robust, with better logging and case-insensitive matching.
    """
    logger.info(
        f"Attempting to get detailed schema for tables: {table_names} from {filepath}"
    )
    try:
        with open(filepath, mode="r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            normalized_target_tables = {name.strip().lower() for name in table_names}

            all_rows = list(reader)

            relevant_rows = [
                row
                for row in all_rows
                if row["table_name"].strip().lower() in normalized_target_tables
            ]

            logger.info(
                f"Found {len(relevant_rows)} relevant column descriptions in {filepath}."
            )

            if not relevant_rows:
                logger.warning(
                    f"No matching rows found in {filepath} for tables {table_names}. Falling back to basic DB schema."
                )
                return db.get_table_info(table_names=table_names)

            table_schemas = {}
            for row in relevant_rows:
                # Use the actual table name from the CSV for consistent casing
                table_name = row["table_name"]
                if table_name not in table_schemas:
                    table_schemas[table_name] = []

                # --- THIS IS THE CORRECTED LINE ---
                # Builds the string using only the columns that exist in your CSV.
                col_info = f"- {row['column_name']}: {row['column_description']}"
                table_schemas[table_name].append(col_info)

            full_schema_str = (
                "Here is the detailed schema for the tables you are allowed to use:\n\n"
            )
            for table, columns in table_schemas.items():
                full_schema_str += f"Table `{table}`:\n"
                full_schema_str += "\n".join(columns)
                full_schema_str += "\n\n"

            logger.info("Successfully built detailed schema string.")
            return full_schema_str.strip()

    except FileNotFoundError:
        logger.error(
            f"FATAL: The data dictionary file was not found at {filepath}. Falling back to basic schema."
        )
        return db.get_table_info(table_names=table_names)
    except Exception as e:
        logger.error(
            f"An unexpected error occurred while reading {filepath}: {e}", exc_info=True
        )
        return db.get_table_info(table_names=table_names)


def route_query(query: str) -> Optional[str]:
    query_words: Set[str] = set(query.lower().split())
    greetings: Set[str] = {"hello", "hi", "hey"}
    thanks: Set[str] = {"thanks", "thank"}
    if greetings.intersection(query_words):
        return "Hello! How can I help you with your fantasy league data?"
    if thanks.intersection(query_words):
        return "You're welcome!"
    return None


def get_relevant_tables(
    user_query: str, history: str, table_descriptions: str
) -> List[str]:
    prompt = f"""
    You are an expert database routing assistant. Your ONLY job is to identify ALL database tables required to fully answer a user's question.

    **Think step-by-step:**
    1.  Analyze the user's question to understand the core information they are asking for.
    2.  Pay close attention to words that imply a need for descriptive names vs. just IDs. For example, if the user asks **"who"** or **"what was the name"**, you MUST include the table that contains names (like `FantasyOwners_LLM` or `FantasyTeams_LLM`).
    3.  Look at the table descriptions to find all tables that contain the necessary information. A single question often requires joining multiple tables.
    4.  Based on this, output a single line containing a comma-separated list of ALL the necessary table names.

    Do NOT add any explanation, conversational text, or prefixes. If no tables are relevant, return an empty string.

    --- CONTEXT ---
    Conversation History:
    {history}

    Available Table Descriptions:
    {table_descriptions}

    User's New Question: {user_query}
    --- END CONTEXT ---

    REQUIRED_TABLES:
    """
    try:
        response = llm.invoke(prompt)
        content = response.content.strip()
        logger.info(f"Table Selector raw output: {content}")
        if ":" in content:
            content = content.split(":")[-1].strip()
        table_list = [table.strip() for table in content.split(",") if table.strip()]
        logger.info(f"Table Selector identified relevant tables: {table_list}")
        return table_list
    except Exception as e:
        logger.error(f"Failed to select relevant tables: {e}")
        return []


# --- Agent Architecture ---
def create_specialized_agent(forced_schema: str):
    """Creates a custom SQL agent with NO schema discovery tools."""

    forced_schema = get_detailed_schema_info(
        table_names=relevant_tables,  # Explicitly map the variable to the parameter
        filepath="data_dictionary.csv",
    )
    tools = [QuerySQLDatabaseTool(db=db)]

    prompt_template = """
    You are an expert AI data analyst. Your job is to answer questions by generating and running SQLite queries.
    You have access to a database with the following tools:

    {tools}

    The only tables you are allowed to query are listed below. Do not assume any other tables or columns exist.
    Do NOT use any tool other than `sql_db_query`.

    **DATABASE SCHEMA:**
    {schema}

    **VERY IMPORTANT INSTRUCTIONS:**
    1.  Take one small step at a time. Do not try to answer the whole question in a single step.
    2.  First, think about the query you need to run. Then, use the `sql_db_query` tool.
    3.  **Do not predict the result of the query.** Wait for the actual "Observation" before you think about the final answer.
    4.  If a query fails, you MUST analyze the error and try to fix the query.

    Use the following format:

    Question: the input question you must answer
    Thought: I need to take a single step to answer the question. I will formulate a query.
    Action: the action to take, should be one of [{tool_names}]
    Action Input: the SQLite query to run
    Observation: the result of the query
    Thought: I have received the result from the query. Now I will analyze it and decide on the next step or the final answer.
    ... (this Thought/Action/Action Input/Observation can repeat N times)
    Thought: I now have enough information to form the final answer.
    Final Answer: the final answer to the original input question

    Begin!

    Conversation History:
    {history}

    Question: {input}
    Thought:{agent_scratchpad}
    """

    prompt = PromptTemplate.from_template(prompt_template).partial(schema=forced_schema)

    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors="Check your output and try again.",
    )


# --- Main Streamlit App ---

# Configure the page
st.set_page_config(page_title="Fantasy Football Oracle", page_icon="🏈")
st.title("🏈 Fantasy Football Oracle")
st.write("Ask me anything about your league's history!")

# Load static resources once using caching
table_descriptions = load_table_descriptions("table_dictionary.csv")

# Initialize stateful conversation memory
if "memory" not in st.session_state:
    st.session_state.memory = ConversationBufferMemory(
        memory_key="history",
        input_key="input",
        return_messages=True,  # Makes it easier to display chat history
    )

# Display chat messages from history on app rerun
for message in st.session_state.memory.chat_memory.messages:
    role = "user" if message.type == "human" else "assistant"
    with st.chat_message(role):
        st.markdown(message.content)

# Main interaction loop, runs when the user types in the chat input
if prompt := st.chat_input("Ask a question about your league..."):
    # Display the user's new message
    with st.chat_message("user"):
        st.markdown(prompt)

    # Begin processing the user's query and displaying the assistant's response
    with st.chat_message("assistant"):
        with st.spinner("The Oracle is thinking..."):
            assistant_response_content = ""

            # 1. First, check for simple, non-DB queries (greetings, etc.)
            simple_response = route_query(prompt)

            if simple_response:
                assistant_response_content = simple_response
                st.markdown(assistant_response_content)
            else:
                # 2. If it's a real question, begin the agentic workflow
                history_str = st.session_state.memory.load_memory_variables({})[
                    "history"
                ]

                relevant_tables = get_relevant_tables(
                    prompt, history_str, table_descriptions
                )

                if not relevant_tables:
                    assistant_response_content = "I could not determine which data tables are relevant for that question. Please be more specific about what you're looking for."
                    st.error(assistant_response_content)
                else:
                    # --- In-App Debugger & Schema Generation ---

                    # THIS IS THE CORRECTED LINE:
                    # We pass the 'relevant_tables' variable, which holds the list of tables.
                    forced_schema = get_detailed_schema_info(
                        table_names=relevant_tables, filepath="data_dictionary.csv"
                    )

                    with st.expander("🕵️ Agent's Internal Context"):
                        st.markdown("**Tables Selected for this Query:**")
                        st.write(relevant_tables)
                        st.markdown("---")
                        st.markdown("**Schema Provided to the Agent:**")
                        st.code(forced_schema, language="text")

                    # --- Agent Execution ---
                    agent_executor = create_specialized_agent(forced_schema)

                    logger.info(
                        f"Invoking agent for tables {relevant_tables} with user prompt."
                    )

                    try:
                        logging_callback = LoggingCallbackHandler()
                        response = agent_executor.invoke(
                            {"input": prompt, "history": history_str},
                            config={"callbacks": [logging_callback]},
                        )
                        assistant_response_content = response["output"]
                        st.markdown(assistant_response_content)

                    except Exception as e:
                        error_message = (
                            f"I encountered an error trying to answer that: {e}"
                        )
                        st.error(error_message)
                        logger.error(f"Agent execution failed: {e}", exc_info=True)
                        assistant_response_content = "Sorry, I ran into a problem and couldn't answer your question. Please check the logs for details."

    # 3. After generating a response, save the turn to memory for future context
    st.session_state.memory.save_context(
        {"input": prompt}, {"output": assistant_response_content}
    )
