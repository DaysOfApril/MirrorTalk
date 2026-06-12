import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\pipelines\profile_builder.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    except Exception as e:
        logger.warning(
            "Primary %s/%s unavailable: %s, falling back to %s/%s",
            primary_provider, primary_model, e, fallback_provider, fallback_model,
        )
        return (
            create_llm(ProviderConfig(provider=fallback_provider, model=fallback_model)),
            fallback_provider,
            fallback_model,
        )'''

new = '''    except Exception as e:
        logger.warning(
            "Primary %s/%s unavailable: %s, falling back to %s/%s",
            primary_provider, primary_model, e, fallback_provider, fallback_model,
        )
        try:
            fallback_llm = create_llm(ProviderConfig(provider=fallback_provider, model=fallback_model))
            await fallback_llm.ainvoke([SystemMessage(content="ping")])
            logger.info("Fallback %s/%s OK", fallback_provider, fallback_model)
            return fallback_llm, fallback_provider, fallback_model
        except Exception as e2:
            logger.error(
                "Fallback %s/%s also failed: %s. Run 'ollama serve' or configure qwen/deepseek API key in Settings.",
                fallback_provider, fallback_model, e2,
            )
            raise RuntimeError(
                f"Both primary ({primary_provider}/{primary_model}) and fallback "
                f"({fallback_provider}/{fallback_model}) are unavailable. "
                f"Please run 'ollama serve' and 'ollama pull {fallback_model}', "
                f"or configure a Qwen/DeepSeek API key in the Settings page."
            ) from e2'''

content = content.replace(old, new)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed _create_llm_with_fallback")
