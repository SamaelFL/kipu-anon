"""Mensajes estilo Slack -> registros normalizados."""


def author_map(users):
    out = {}
    for u in users:
        name = (u.get("real_name") or (u.get("profile") or {}).get("real_name") or "").strip()
        if not name or u.get("deleted"):
            name = u.get("name") or name
        out[u["id"]] = name
    return out


def message_record(canal, m, authors):
    uid = m.get("user")
    if m.get("subtype") == "bot_message" and m.get("username"):
        author = m["username"]
    else:
        author = authors.get(uid) or m.get("username") or ""
    ts = m.get("ts", "")
    return {
        "id": m.get("client_msg_id"),
        "thread_id": "%s:%s" % (canal, m.get("thread_ts") or ts),
        "author": author,
        "ts": ts,
        "text": m.get("text", ""),
        "attachments": [{"filename": f.get("name", "")} for f in (m.get("files") or [])],
    }
