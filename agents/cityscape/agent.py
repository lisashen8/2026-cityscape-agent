"""
Defines the multi-agent Cityscape workflow using the Agent Development Kit (ADK).
It orchestrates landmark research, weather lookup via Google Maps MCP, and local time calculation in parallel.
The gathered context is then passed to the Nano Banana (Gemini) image generation model to produce a stylized 3D cityscape.
"""

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams, StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.tools import google_search
from google.adk.tools.tool_context import ToolContext

import datetime
from google.genai import types
import os

DEFAULT_MODEL='gemini-3.5-flash'
NANO_BANANA_MODEL='gemini-3-pro-image'

# Remote MCP server (Google Maps Platform) reached over streamable HTTP.
# Provides the weather lookup used by the city_current_weather agent.
get_weather = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://mapstools.googleapis.com/mcp",
        # API key is read from the environment; .strip() guards against a
        # trailing newline when the value comes from a file or secret mount.
        headers={"X-Goog-Api-Key": os.environ.get("MAPS_API_KEY", "").strip() }
    ),
)

# Local MCP server launched as a subprocess over stdio. The `mcp-gemini-go`
# binary exposes the Nano Banana image generation tool.
nano_banana = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="mcp-gemini-go",
            args=[],
            # Inherit the parent env and pin PROJECT_ID so the binary
            # knows which GCP project to bill/authenticate against.
            env=dict(os.environ, PROJECT_ID=os.environ.get("GOOGLE_CLOUD_PROJECT", "")),
        ),
        # Generous timeout: image generation is much slower than a normal tool call.
        timeout=60,
    ),
)

async def display_image_with_adk(image_path: str, tool_context: ToolContext):
    """Reads an image file from the local disk and displays it in the chat as an artifact."""

    try:
        # Read as binary; the image was just written to disk by the nano_banana tool.
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        # Registers the bytes as an ADK artifact, which is what makes the
        # image render inline in the chat UI.
        await tool_context.save_artifact(
            # Artifact name shown to the user (filename only, not the full path).
            os.path.basename(image_path),
            # Wrap raw bytes in a genai Part so the client knows to render a PNG.
            types.Part.from_bytes(data=image_bytes, mime_type='image/png'),
        )
        return {
            'status': 'success',
            'detail': f'Image "{os.path.basename(image_path)}" displayed successfully.',
        }
    except FileNotFoundError:
        # The model may hallucinate a path; report it back so it can retry.
        return {"status": "failed", "detail": f"Image file not found at path: {image_path}"}
    except Exception as e:
        # Catch-all so a tool failure never takes down the agent run.
        return {"status": "failed", "detail": f"An error occurred: {e}"}

# Research agent #1: grounded landmark lookup via Google Search.
# Result lands in shared state under "city_profile".
city_profile = LlmAgent(
    model=DEFAULT_MODEL,
    name='city_researcher',
    description="Find most iconic city attributes.",
    instruction="Use the Google search tool to figure out the most iconic landmark and immediate geographical attributes (lakes, major rivers, hills etc.) in a given city and return a ordered list starting with the most important landmarks.",
    tools=[google_search],
    output_key="city_profile"
)

# Research agent #2: live conditions via the Google Maps MCP toolset.
# Result lands in shared state under "city_weather".
city_current_weather = LlmAgent(
    model=DEFAULT_MODEL,
    name='city_current_weather',
    description="Looks up the current weather to be used in the city image.",
    instruction="Use the available tool to get a summary of current weather conditions in a city to provide the image with up to date information.",
    tools=[get_weather],
    output_key="city_weather"
)

# Demoing how the Cloud Run sandbox is invoked to execute a Python script.
# Instead of running get_time.py in-process, we shell out to the sandbox
# binary provided by Cloud Run, which executes the script in an isolated
# environment with network access disabled by default.
def get_time_for_city(city: str) -> str:
    """Gets the current local time for a given city."""
    import subprocess
    import os
    
    # Cloud Run mounts this binary; its presence is how we detect the
    # managed environment vs. a local dev machine.
    sandbox_path = "/usr/local/gcp/bin/sandbox"
    # The helper script lives at the repo root, alongside main.py.
    script_path = os.path.join(os.getcwd(), "get_time.py")
    
    if os.path.exists(sandbox_path):
        import sys
        import os
        print(f"Executing time script inside Cloud Run sandbox for city: {city}")
        # We must pass the --allow-egress flag to the sandbox binary so the 
        # python script inside the sandbox can make outbound HTTP requests 
        # to the Google Maps Geocoding and Timezone APIs. Without this flag, 
        # the sandbox completely blocks all network access.
        # MAPS_API_KEY is forwarded explicitly because the sandbox starts
        # with a clean environment.
        cmd = [sandbox_path, "do", "--allow-egress", "--env", f"MAPS_API_KEY={os.environ.get('MAPS_API_KEY', '')}", "--", sys.executable, script_path, city]
    else:
        import sys
        print(f"Executing time script locally (no sandbox) for city: {city}")
        # sys.executable keeps us on the same interpreter/venv as the agent.
        cmd = [sys.executable, script_path, city]
        
    try:
        # check=True turns a non-zero exit code into CalledProcessError so
        # failures surface here instead of returning an empty string.
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"Execution successful. Time retrieved: {result.stdout.strip()}")
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # Return the error as a string so the LLM can report it verbatim
        # rather than crashing the whole agent run.
        print(f"Execution failed. Error: {e.stderr}")
        return f"Error getting time: {e.stderr}"


# Wraps the plain Python function above as an agent tool. The instruction is
# emphatic because LLMs otherwise tend to invent a plausible-looking time.
city_current_time = LlmAgent(
    model=DEFAULT_MODEL,
    name='city_current_time',
    description="Looks up the current time in the city.",
    instruction="Use the available tool to get the current local time in the city to provide the image with up to date information. CRITICAL: You MUST use the exact time returned by the get_time_for_city tool. Do NOT guess or hallucinate the time. If the tool returns an error, output the exact error message.",
    tools=[get_time_for_city],
    output_key="city_time"
)

# Fan-out step: runs the landmark, weather, and time agents concurrently.
# Each sub-agent writes to its own output_key, so results are merged into
# shared state without overwriting one another.
city_info = ParallelAgent(
    name="city_info",
    sub_agents=[city_profile, city_current_weather, city_current_time]
)

# Fan-in step: consumes the collected city context and drives image generation.
# The instruction is an f-string so today's date and the working directory are
# baked in at import time.
city_drawer = LlmAgent(
    model=DEFAULT_MODEL,
    name='city_drawer',
    description="Draws the cityscape picture.",
    instruction=f"""
    Image Context:
    - Current Date: {datetime.date.today().strftime("%A, %B %d, %Y")}
    - Current Time in the City
    - Current Weather
    - Most Prominent Landmarks in that City

    Image Model: {NANO_BANANA_MODEL}

    Instructions:
    1. Come up with an absolute directory path for the cityscape of the current city 
        and make sure it's added to the current folder's 'generated' folder 
        e.g. {os.getcwd()}/generated/zurich/ for a cityscape of Zurich.
    2. Use the `nano_banana` tool with the specified image model to create the image.
        CRITICAL: You MUST pass the directory path from step 1 as the `output_directory` argument!
        Follow these instructions carefully for the image prompt:
        
        Present a clear, 45° top-down isometric miniature 3D cartoon scene of [CITY], 
        featuring its most iconic landmarks and architectural elements. Use soft, 
        refined textures with realistic PBR materials and gentle, lifelike 
        lighting and shadows. Integrate the current weather conditions directly 
        into the city environment to create an immersive atmospheric mood.
        Use a clean, minimalistic composition with a soft, solid-colored background.
        At the top-center, place the title “[CITY]” in large bold text, a prominent
        weather icon beneath it, then the current date, time and temperature (medium text).
        All text must be centered with consistent spacing, and may subtly overlap the 
        tops of the buildings.
        Square 1080x1080 dimension.
        
    3. Use the `display_image_with_adk` tool with the absolute file path of the generated image.
    """,
    # Two tools: `nano_banana` writes the PNG to disk, then
    # `display_image_with_adk` loads it back and renders it in the chat.
    tools=[nano_banana, display_image_with_adk]
)

# Entry point discovered by ADK. Runs the pipeline in order:
# gather city context (parallel) -> generate and display the image.
root_agent = SequentialAgent(
    name='cityscape_agent',
    description="Creates AI-generated pictures of cities based on the current weather and their unique properties.",
    sub_agents=[city_info, city_drawer],
)
