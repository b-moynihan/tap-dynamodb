import backoff
import boto3
import singer

from botocore.credentials import (
    AssumeRoleCredentialFetcher,
    CredentialResolver,
    DeferredRefreshableCredentials,
    JSONFileCache
)
from botocore.session import Session
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

LOGGER = singer.get_logger()
REQUEST_TIMEOUT = 300

def retry_pattern():
    return backoff.on_exception(backoff.expo,
                                (ClientError, ConnectTimeoutError, ReadTimeoutError),
                                max_tries=5,
                                on_backoff=log_backoff_attempt,
                                factor=10)


def log_backoff_attempt(details):
    LOGGER.info("Error detected communicating with Amazon, triggering backoff: %d try", details.get("tries"))


class AssumeRoleProvider():
    METHOD = 'assume-role'

    def __init__(self, fetcher):
        self._fetcher = fetcher

    def load(self):
        return DeferredRefreshableCredentials(
            self._fetcher.fetch_credentials,
            self.METHOD
        )


@retry_pattern()
def setup_aws_client(config):
    role_arn = "arn:aws:iam::{}:role/{}".format(config['account_id'].replace('-', ''),
                                                config['role_name'])

    session = Session()
    fetcher = AssumeRoleCredentialFetcher(
        session.create_client,
        session.get_credentials(),
        role_arn,
        extra_args={
            'DurationSeconds': 3600,
            'RoleSessionName': 'TapDynamodDB',
            'ExternalId': config['external_id']
        },
        cache=JSONFileCache()
    )

    refreshable_session = Session()
    refreshable_session.register_component(
        'credential_provider',
        CredentialResolver([AssumeRoleProvider(fetcher)])
    )

    LOGGER.info("Attempting to assume_role on RoleArn: %s", role_arn)
    boto3.setup_default_session(botocore_session=refreshable_session)

def get_request_timeout(config):
    # if request_timeout is other than 0,"0" or "" then use request_timeout
    request_timeout = config.get('request_timeout')
    if request_timeout and float(request_timeout):
        request_timeout = float(request_timeout)
    else: # If value is 0,"0" or "" then set default to 300 seconds.
        request_timeout = REQUEST_TIMEOUT
    return request_timeout

def get_client(config):
    # get the request_timeout
    request_timeout = get_request_timeout(config)
    # add the request_timeout in both connect_timeout as well as read_timeout
    timeout_config = Config(connect_timeout=request_timeout, read_timeout=request_timeout)
    if config.get('use_local_dynamo'):
        return boto3.client('dynamodb',
                            endpoint_url='http://localhost:8000',
                            region_name=config['region_name'],
                            config=timeout_config   # pass the config to add the request_timeout
                            )
    return boto3.client('dynamodb', config['region_name'],
                        config=timeout_config   # pass the config to add the request_timeout
                        )

def get_stream_client(config):
    # get the request_timeout
    request_timeout = get_request_timeout(config)
    # add the request_timeout in both connect_timeout as well as read_timeout
    timeout_config = Config(connect_timeout=request_timeout,  read_timeout=request_timeout)
    if config.get('use_local_dynamo'):
        return boto3.client('dynamodbstreams',
                            endpoint_url='http://localhost:8000',
                            region_name=config['region_name'],
                            config=timeout_config   # pass the config to add the request_timeout
                            )
    return boto3.client('dynamodbstreams',
                        region_name=config['region_name'],
                        config=timeout_config   # pass the config to add the request_timeout
                        )
