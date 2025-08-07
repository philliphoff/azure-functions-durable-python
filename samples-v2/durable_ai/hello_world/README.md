# A "Hello World!" sample of Azure Durable Functions with OpenAI Agents SDK

## Prerequisites

 - An Azure OpenAI instance with a deployed model
 - A running Durable Task Scheduler (DTS) instance (or emulator)

## Setup

1. Ensure the following values have been added to `local.settings.json`:

   - `AZURE_OPENAI_API_KEY`: The API key for the Azure OpenAI instance
   - `AZURE_OPENAI_API_VERSION`: The version (e.g. `2024-08-01-preview`) of the Azure OpenAI instance
   - `AZURE_OPENAI_ENDPOINT`: The endpoint of the Azure OpenAI instance (e.g.  `https://<name>.openai.zaure.com/`)
   - `AZURE_OPENAI_DEPLOYMENT`: The name of the deployed model
   - `DURABLE_TASK_SCHEDULER_CONNECTION_STRING`: The connection string to the DTS instance (e.g. `Endpoint=http://localhost:8080;Authentication=None`)
   - `TASKHUB_NAME`: The name of the DTS taskhub (e.g. `default`)

## Running the Sample

1. Ensure Azurite is started
1. Ensure the DTS instance is started
1. Open this folder as a workspace in VS Code (i.e. not the root folder)
1. F5 the workspace and wait for the Azure Functions host to start
1. Submit a GET request to the Azure Functions endpoint to invoke the agent with input passed as the query parameter `input`
   ```bash
   curl -G "http://localhost:7071/api/agents/myagent" --data-urlencode "input=Write a haiku about Portland, Oregon"
   ```
1. Wait for the orchestration to complete, then either view the results using the returned status URL or in the DTS dashboard