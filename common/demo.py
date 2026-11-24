import uuid
def demo_subject(username):
    # Deterministic identifiers coordinate explicitly fictional local seed accounts only.
    return uuid.uuid5(uuid.NAMESPACE_URL,'civicbridge-local-demo:'+username)
