import logging
from collections.abc import AsyncIterable

from livekit.agents import Agent, llm
from prompt import PROMPT
from rule_kb import build_user_context_block, match_rules

logger = logging.getLogger("agent")


class Assistant(Agent):
    def __init__(self) -> None:
        self._turn_index = 0
        self._rule_context_block = ""
        super().__init__(
            instructions=PROMPT,
        )

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        self._turn_index += 1
        user_text = (new_message.text_content or "").strip()
        hits = match_rules(user_text, max_hits=2) if user_text else []
        self._rule_context_block = build_user_context_block(hits) if hits else ""
        if hits:
            logger.info(
                "rule_kb.hit.on_user_turn_completed",
                extra={"rule_ids": [h.rule_id for h in hits], "user_text": user_text},
            )

    @staticmethod
    def _latest_user_text(chat_ctx: llm.ChatContext) -> str:
        msgs = getattr(chat_ctx, "messages", [])
        if callable(msgs):
            msgs = msgs()
        msg_list = list(msgs or [])
        for msg in reversed(msg_list):
            if getattr(msg, "role", None) == "user":
                return (msg.text_content or "").strip()
        return ""

    def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings,
    ) -> AsyncIterable[llm.ChatChunk | str]:
        run_ctx = chat_ctx
        # Recompute rule hit from latest chat context to avoid stale/missed cache.
        latest_user_text = self._latest_user_text(chat_ctx)
        hits = match_rules(latest_user_text, max_hits=2) if latest_user_text else []
        block = build_user_context_block(hits) if hits else self._rule_context_block

        if hits:
            logger.info(
                "rule_kb.hit.llm_node",
                extra={"rule_ids": [h.rule_id for h in hits], "user_text": latest_user_text},
            )

        if block:
            run_ctx = chat_ctx.copy()
            run_ctx.add_message(role="system", content=block)

        async def _stream() -> AsyncIterable[llm.ChatChunk | str]:
            async for chunk in Agent.default.llm_node(self, run_ctx, tools, model_settings):
                yield chunk

        return _stream()
