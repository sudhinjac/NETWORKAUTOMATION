from ncclient import manager
import xml.etree.ElementTree as ET

router = {
    "host": "ios-xe-mgmt-latest.cisco.com",
    "port": 10000,
    "username": "developer",
    "password": "c1sco12345"
}

with manager.connect(
    host=router["host"],
    port=router["port"],
    username=router["username"],
    password=router["password"],
    hostkey_verify=False,
    device_params={'name':'default'}
) as m:
    
    # Retrieve the YANG schema
    ip_schema = m.get_schema('ietf-ip')
    
    # Parse the XML to get the YANG text
    root = ET.fromstring(str(ip_schema))
    # In IOS-XE, schema text is inside <data> -> <schema-text>
    ns = {'nc': 'urn:ietf:params:xml:ns:netconf:base:1.0'}
    yang_text_elem = root.find('.//{*}schema-text')
    
    if yang_text_elem is not None:
        yang_text = yang_text_elem.text
        # Save to file
        with open('ietf-ip.yang', 'w') as f:
            f.write(yang_text)
        print("YANG schema saved to 'ietf-ip.yang'")
    else:
        print("Could not find schema text in the response")