from mezzanine.conf import settings

welcome_reply_to = settings.WELCOME_REPLY_TO
test_reply_to = settings. TEST_REPLY_TO


def get_reply_to(subscription):
    try:
        welcome = True if 'zugewandert' in subscription.newsletter.slug else False
        test = True if 'test-newsletter' == subscription.newsletter.slug else False
    except:
        return []
    else:
        if welcome:
            return welcome_reply_to
        elif test:
            return test_reply_to
    return []
