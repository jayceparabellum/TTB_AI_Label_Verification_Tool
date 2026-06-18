"""Agent graph state: the conversation plus three context anchors.

The anchors let pronouns resolve across turns ("approve that one", "re-check the
label") without the model having to restate ids.
"""

from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # Conversation history; add_messages appends rather than overwrites.
    messages: Annotated[list, add_messages]
    # The uploaded label currently in focus (key into the image store). The model
    # never supplies this — tools read it from state, so it can't be hallucinated.
    active_image_id: Optional[str]
    # Claimed application values the user is verifying against.
    expected: Optional[dict]          # {"brand": str, "alcohol_content": str, ...}
    # Id of the most recent verification result (for "approve/override that one").
    last_result_id: Optional[str]
