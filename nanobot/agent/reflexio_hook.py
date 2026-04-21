import os
import httpx
from nanobot.agent.hook import AgentHook, AgentHookContext
from loguru import logger


class ReflexioHook(AgentHook):
    def __init__(self, bus=None):
        super().__init__()
        self.bus = bus
        self.url = os.environ.get('REFLEXIO_URL', 'http://reflexio-sidecar:8081')

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Publish interaction to reflexio for future memory retrieval."""
        # Check if this is the final iteration (stop_reason is set)
        if context.stop_reason and context.final_content:
            try:
                # Find the last user message in history
                user_msg = None
                for msg in reversed(context.messages):
                    if msg.get('role') == 'user':
                        content = msg.get('content')
                        if isinstance(content, list):
                            text_parts = [p['text'] for p in content if p.get('type') == 'text']
                            user_msg = ' '.join(text_parts)
                        else:
                            user_msg = str(content)
                        break

                if user_msg:
                    # Clean up user_msg if it contains runtime context
                    if '<!-- nanobot_runtime_context -->' in user_msg:
                        user_msg = user_msg.split('-->', 1)[-1].strip()
                    if '[Runtime Context' in user_msg:
                        marker = '[/Runtime Context]'
                        idx = user_msg.find(marker)
                        if idx != -1:
                            user_msg = user_msg[idx + len(marker):].strip()

                    payload = {
                        'user_id': 'default_user',
                        'interaction_data_list': [
                            {'role': 'user', 'content': user_msg},
                            {'role': 'assistant', 'content': context.final_content}
                        ],
                        'session_id': 'default_session'
                    }

                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            f'{self.url}/api/publish_interaction',
                            json=payload,
                            timeout=5.0
                        )
                        if resp.is_success:
                            logger.info('Reflexio: Interaction published successfully')
                        else:
                            logger.warning(f'Reflexio: Failed to publish: {resp.status_code}')
            except Exception as e:
                logger.error(f'Reflexio: Error in hook: {e}')
