"""Expose pytest JUnit failures as GitHub annotations (logs/artifacts may need login)."""
import sys
from xml.etree import ElementTree


def report(path):
    root = ElementTree.parse(path).getroot()
    for case in root.iter('testcase'):
        for kind in ('failure', 'error'):
            failure = case.find(kind)
            if failure is not None:
                text = f"{case.get('classname')}.{case.get('name')}\n{failure.text or failure.get('message', '')}"
                text = text[:20000].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
                print('::error title=Automated test failure::' + text)


if __name__ == '__main__':
    report(sys.argv[1])
