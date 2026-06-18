from paperbot.line import split_messages


def test_split_messages_respects_limit():
    text = "first paragraph\n\n" + ("x" * 25) + "\n\nlast"
    messages = split_messages(text, limit=20)
    assert all(len(message) <= 20 for message in messages)
    assert "first paragraph" in messages[0]
    assert messages[-1].endswith("last")


def test_short_message_is_unchanged():
    assert split_messages("hello", limit=20) == ["hello"]

