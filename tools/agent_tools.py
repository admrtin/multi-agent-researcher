import dataclasses

def save_markdown_file(filename: str, content: str):
    """
    Saves a research plan to a markdown (.md) file in the current directory.
    Args:
        filename: The name of the file (e.g., 'aspect_1_analysis.md').
        content: The full markdown content to be saved.
    """
    # Ensure the filename ends in .md
    if not filename.endswith(".md"):
        filename += ".md"
        
    with open(filename, "w") as f:
        f.write(content)
    return f"Successfully saved {filename} to disk."

from dataclasses import dataclass

@dataclass(frozen=True)
class GeminiModel:
    """
    Centralized model spec for the multi-agent research system.
    Allocates model power based on task complexity/cost.
    """
    ROOT: str = "gemini-3-flash"
    PLANNER: str = "gemini-3-flash"
    RESEARCHER: str = "gemini-3-flash"
    SYNTHESIZER: str = "gemini-3-flash"

# Instance for easy import
gemini_models = GeminiModel()