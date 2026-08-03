from xml.etree import ElementTree as ET

OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"


def serialize_opensearch_description(search_url_template: str) -> bytes:
    root = ET.Element("OpenSearchDescription", {"xmlns": OPENSEARCH_NS})
    ET.SubElement(root, "ShortName").text = "Shuku Starship"
    ET.SubElement(root, "Description").text = "Search the Shuku catalog"
    ET.SubElement(
        root,
        "Url",
        {
            "type": "application/atom+xml;profile=opds-catalog;kind=navigation",
            "template": search_url_template,
        },
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


__all__ = ["serialize_opensearch_description"]
