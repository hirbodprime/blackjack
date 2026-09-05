"""Resolve language from the conversation that produced a bot response."""

from asgiref.sync import sync_to_async

from game.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from game.models import Group, Player, UserSettings


GROUP_CHAT_TYPES = {"group", "supergroup"}


def group_language(chat_id: int | str) -> str:
    group = Group.objects.filter(group_chat_id=str(chat_id)).order_by("pk").first()
    return group.language if group and group.language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def player_language(player_id: int) -> str:
    settings = UserSettings.objects.filter(player_id=player_id).only("language").first()
    return settings.language if settings and settings.language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def language_for_context(*, chat_id: int | str | None, chat_type: str | None, player_id: int | None = None) -> str:
    if chat_id is not None and chat_type in GROUP_CHAT_TYPES:
        return group_language(chat_id)
    if player_id is not None:
        return player_language(player_id)
    return DEFAULT_LANGUAGE


async def language_for_update(update) -> str:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    return await sync_to_async(language_for_context, thread_sensitive=True)(
        chat_id=getattr(chat, "id", None),
        chat_type=getattr(chat, "type", None),
        player_id=getattr(user, "id", None),
    )


def set_group_language_sync(chat_id: int | str, chat_name: str | None, language: str) -> Group:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("Unsupported language")
    group = Group.objects.filter(group_chat_id=str(chat_id)).order_by("pk").first()
    if group is None:
        group = Group(group_chat_id=str(chat_id), group_name=chat_name)
    elif chat_name and group.group_name != chat_name:
        group.group_name = chat_name
    group.language = language
    group.save()
    return group


set_group_language = sync_to_async(set_group_language_sync, thread_sensitive=True)
