"""Agent state definition for the LangGraph workflow.

AgentState flows through the graph: start_node -> 4 parallel agents -> core_analysis.
The ``data`` dict carries analysis results between nodes; ``messages`` accumulates
LangChain messages; ``metadata`` holds run-level bookkeeping.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, Sequence, TypedDict

from langchain_core.messages import BaseMessage


def merge_dicts(d1: Dict[str, Any], d2: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dicts — values in *d2* overwrite *d1*."""
    return {**d1, **d2}


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    data: Annotated[Dict[str, Any], merge_dicts]
    metadata: Annotated[Dict[str, Any], merge_dicts]
