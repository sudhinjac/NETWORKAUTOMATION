"""
Collection of unit tests to test various resolutions for connectivity to device
"""
# Modules
import os
from pygnmi.client import gNMIclient


# Statics
ENV_USERNAME = os.getenv("PYGNMI_USER")
ENV_PASSWORD = os.getenv("PYGNMI_PASS")
ENV_ADDRESS = os.getenv("PYGNMI_HOST")
ENV_HOSTNAME = os.getenv("PYGNMI_NAME")
ENV_PORT = os.getenv("PYGNMI_PORT")
ENV_PATH_CERT = os.getenv("PYGNMI_CERT")
ENV_FAKE_HOSTNAME = os.getenv("PYGNMI_FAKE_NAME")


# Tests
def test_ipv4_address_certificate_download():
    """
    Unit test to test connectivity to gNMI speaking network function over secure channel
    with the certificate download
    """
    gconn = gNMIclient(target=(ENV_HOSTNAME, ENV_PORT),
                       username=ENV_USERNAME,
                       password=ENV_PASSWORD)
    gconn.connect()

    result = gconn.capabilities()

    gconn.close()

    assert "supported_models" in result
    assert "supported_encodings" in result
    assert "gnmi_version" in result

    del gconn


def test_ipv4_address_certificate_download_without_validation():
    """
    Unit test to test connectivity to gNMI speaking network function over secure channel
    with the certificate download
    """
    gconn = gNMIclient(target=(ENV_FAKE_HOSTNAME, ENV_PORT),
                       username=ENV_USERNAME,
                       password=ENV_PASSWORD,
                       skip_verify=True)
    gconn.connect()

    result = gconn.capabilities()

    gconn.close()

    assert "supported_models" in result
    assert "supported_encodings" in result
    assert "gnmi_version" in result

    del gconn
