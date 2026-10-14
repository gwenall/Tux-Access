"""Convert the recovered interface inventory to an implementation-neutral table."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('inventory', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
inventory = json.loads(args.inventory.read_text(encoding='utf-8'))
messages = {}
def walk(items, prefix):
    for message in items:
        name = prefix + '.' + message['name']
        messages[name] = message['fields']
        walk(message['messages'], name)
for file in inventory['files']:
    walk(file['messages'], '.' + file['package'])
args.output.write_text(
    '# Independently recovered protobuf field metadata; see protocol-findings.txt.\n'
    'SCHEMA = ' + repr(messages) + '\n', encoding='utf-8')
print(f'Generated {len(messages)} message schemas.')
