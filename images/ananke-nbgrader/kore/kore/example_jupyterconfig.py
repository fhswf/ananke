import logging
import os
import sys
from ltiauthenticator import LTIAuthenticator
import MultiAuthenticator
from oauthenticator.generic import GenericOAuthenticator
# ===========================================================================
#                            Extra Configuration
# ===========================================================================

print("loading extra conf: " + __file__)
c = get_config()  # noqa
