#!/usr/bin/env python3
"""
L5X Splitter - Splits a monolithic L5X file into individual routine files.

Creates an l5x_individual/ folder alongside the source L5X containing:
  - One XML file per routine (Program--Routine.xml)
  - AOI routines as AOI--Name--Routine.xml
  - _index.json:  Project structure, routine relationships, JSR call graph
  - _tags.csv:    All tags with metadata for navigation
  - _cross_references.json: Tag usage cross-references across routines

Usage:
    python split_l5x.py <path/to/file.l5x>
    python split_l5x.py <directory>          # Process all L5X files recursively

Zero external dependencies - uses only Python stdlib.
"""

import argparse
import csv
import json
import re
import shutil
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Matches PLC tag paths: Tag, Tag.Member, Tag[0].Sub, Tag[0,1].X, etc.
TAG_REF_PATTERN = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*'
    r'(?:\.[A-Za-z_][A-Za-z0-9_]*)*'
    r'(?:\[[^\]]+\])*'
    r'(?:\.[A-Za-z_][A-Za-z0-9_]*)*)'
)

# Instruction(operands)
INSTRUCTION_PATTERN = re.compile(
    r'([A-Z_][A-Z0-9_]*)\s*\(([^)]*)\)',
    re.IGNORECASE,
)

# Instructions whose destination operand is a write
DEST_OPERAND_INDEX = {
    'OTE': 0, 'OTL': 0, 'OTU': 0, 'RES': 0, 'CLR': 0,
    'CTU': 0, 'CTD': 0, 'TON': 0, 'TOF': 0, 'RTO': 0,
    'MOV': 1, 'MVM': 1, 'COP': 1, 'FLL': 1, 'CPS': 1,
    'ADD': 2, 'SUB': 2, 'MUL': 2, 'DIV': 2,
    'CPT': 0, 'SSV': 0, 'GSV': 1, 'MSG': 0,
}

READ_ONLY_INSTRUCTIONS = {
    'XIC', 'XIO', 'ONS', 'OSR', 'OSF',
    'EQU', 'NEQ', 'LES', 'LEQ', 'GRT', 'GEQ', 'MEQ', 'LIM', 'CMP',
    'JSR', 'SBR', 'RET', 'JMP', 'LBL', 'NOP', 'AFI',
}

NUMERIC_LITERAL = re.compile(r'^-?\d+(\.\d+)?([eE][+-]?\d+)?$')
SKIP_TOKENS = {'TRUE', 'FALSE'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Make a string safe for use as a filename."""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def is_literal(token: str) -> bool:
    """Return True if the token is a numeric literal or boolean keyword."""
    return bool(NUMERIC_LITERAL.match(token)) or token.upper() in SKIP_TOKENS


def extract_tag_refs(text: str) -> set:
    """Extract base tag names referenced in rung neutral text."""
    refs = set()
    for m in INSTRUCTION_PATTERN.finditer(text):
        operands_text = m.group(2)
        for op in operands_text.split(','):
            op = op.strip()
            for tm in TAG_REF_PATTERN.finditer(op):
                ref = tm.group(1)
                base = ref.split('.')[0].split('[')[0]
                if base and not is_literal(base):
                    refs.add(base)
    return refs


def extract_jsr_targets(text: str) -> list:
    """Extract JSR target routine names from rung text."""
    targets = []
    for m in re.finditer(r'JSR\s*\(([^,)]+)', text, re.IGNORECASE):
        target = m.group(1).strip()
        if target:
            targets.append(target)
    return targets


def get_description(elem) -> str:
    """Extract description text from an element."""
    desc = elem.find('Description')
    if desc is not None:
        # Direct text (CDATA or plain)
        if desc.text and desc.text.strip():
            return desc.text.strip()
        # Localized variant
        for child in desc:
            if child.text and child.text.strip():
                return child.text.strip()
    return ''


# ---------------------------------------------------------------------------
# Tag index
# ---------------------------------------------------------------------------

def build_tag_index(controller_elem) -> dict:
    """Build {(scope, name): tag_info} for all tags in the project."""
    tags = {}

    # Controller-scope tags (direct children of Controller/Tags)
    ctrl_tags = controller_elem.find('Tags')
    if ctrl_tags is not None:
        for tag_el in ctrl_tags.findall('Tag'):
            name = tag_el.get('Name', '')
            tags[('Controller', name)] = _tag_dict(tag_el, 'Controller')

    # Program-scope tags
    for prog_el in controller_elem.findall('.//Programs/Program'):
        prog_name = prog_el.get('Name', '')
        prog_tags = prog_el.find('Tags')
        if prog_tags is not None:
            for tag_el in prog_tags.findall('Tag'):
                name = tag_el.get('Name', '')
                tags[(prog_name, name)] = _tag_dict(tag_el, prog_name)

    return tags


def _tag_dict(tag_el, scope: str) -> dict:
    return {
        'name': tag_el.get('Name', ''),
        'data_type': tag_el.get('DataType', ''),
        'scope': scope,
        'description': get_description(tag_el),
        'alias_for': tag_el.get('AliasFor', ''),
        'external_access': tag_el.get('ExternalAccess', ''),
        'tag_class': tag_el.get('Class', 'Standard'),
        'constant': tag_el.get('Constant', 'false'),
        'dimensions': tag_el.get('Dimensions', ''),
    }


def resolve_tag(base_name: str, program_name: str, tag_index: dict):
    """Resolve tag by name; program scope first, then controller scope."""
    key = (program_name, base_name)
    if key in tag_index:
        return tag_index[key]
    key = ('Controller', base_name)
    if key in tag_index:
        return tag_index[key]
    return None


# ---------------------------------------------------------------------------
# Routine XML writer
# ---------------------------------------------------------------------------

def write_routine_xml(filepath, routine_elem, *, source_file, controller,
                      program, main_routine, tag_refs, tag_index, prog_name):
    """Write an individual routine XML file with metadata envelope."""
    rtn_name = routine_elem.get('Name', '')
    rtn_type = routine_elem.get('Type', 'RLL')

    wrapper = ET.Element('RoutineExport')
    wrapper.set('SourceFile', source_file)
    wrapper.set('Controller', controller)
    wrapper.set('Program', program)
    wrapper.set('MainRoutine', main_routine)
    wrapper.set('RoutineName', rtn_name)
    wrapper.set('RoutineType', rtn_type)

    # Deep-copy the original routine element (preserves all children)
    wrapper.append(deepcopy(routine_elem))

    # Append a ReferencedTags summary
    if tag_refs:
        ref_section = ET.SubElement(wrapper, 'ReferencedTags')
        for base in sorted(tag_refs):
            info = resolve_tag(base, prog_name, tag_index)
            if info:
                t = ET.SubElement(ref_section, 'Tag')
                t.set('Name', info['name'])
                t.set('DataType', info['data_type'])
                t.set('Scope', info['scope'])
                if info['description']:
                    t.set('Description', info['description'])
                if info['alias_for']:
                    t.set('AliasFor', info['alias_for'])

    tree = ET.ElementTree(wrapper)
    ET.indent(tree, space='  ')
    tree.write(str(filepath), encoding='utf-8', xml_declaration=True)


# ---------------------------------------------------------------------------
# Cross-reference builder
# ---------------------------------------------------------------------------

def update_xref(xref, tag_info, filename, prog_name, rtn_name, rung_num, access):
    """Accumulate a tag usage into the cross-reference dictionary."""
    tag_key = f"{tag_info['scope']}::{tag_info['name']}"
    if tag_key not in xref:
        xref[tag_key] = {
            'name': tag_info['name'],
            'data_type': tag_info['data_type'],
            'scope': tag_info['scope'],
            'description': tag_info['description'],
            'alias_for': tag_info['alias_for'],
            'used_in': [],
        }
    # Find existing usage entry for this file+access pair
    for entry in xref[tag_key]['used_in']:
        if entry['file'] == filename and entry['access'] == access:
            if rung_num not in entry['rungs']:
                entry['rungs'].append(rung_num)
            return
    # New entry
    xref[tag_key]['used_in'].append({
        'file': filename,
        'program': prog_name,
        'routine': rtn_name,
        'rungs': [rung_num],
        'access': access,
    })


def process_rung_xref(rung_text, rung_num, filename, prog_name, rtn_name,
                       tag_index, xref):
    """Scan a rung's neutral text and accumulate cross-references."""
    for instr_match in INSTRUCTION_PATTERN.finditer(rung_text):
        instruction = instr_match.group(1).upper()
        operands_text = instr_match.group(2)
        operands = [o.strip() for o in operands_text.split(',')] if operands_text else []
        dest_idx = DEST_OPERAND_INDEX.get(instruction)
        is_ro = instruction in READ_ONLY_INSTRUCTIONS

        for idx, operand in enumerate(operands):
            for tm in TAG_REF_PATTERN.finditer(operand):
                ref = tm.group(1)
                base = ref.split('.')[0].split('[')[0]
                if not base or is_literal(base):
                    continue
                tag_info = resolve_tag(base, prog_name, tag_index)
                if not tag_info:
                    continue
                if not is_ro and dest_idx is not None and idx == dest_idx:
                    access = 'write'
                else:
                    access = 'read'
                update_xref(xref, tag_info, filename, prog_name, rtn_name,
                            rung_num, access)


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_l5x(l5x_path: Path, verbose: bool = False):
    """Process a single L5X file and generate the split output."""
    if verbose:
        print(f'Processing: {l5x_path}')

    tree = ET.parse(str(l5x_path))
    root = tree.getroot()

    controller_elem = root.find('.//Controller')
    if controller_elem is None:
        print(f'  ERROR: No Controller element in {l5x_path}')
        return

    controller_name = controller_elem.get('Name', '')
    processor_type = controller_elem.get('ProcessorType', '')
    source_filename = l5x_path.name

    # Output directory
    out_dir = l5x_path.parent / 'l5x_individual'
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir()

    tag_index = build_tag_index(controller_elem)

    # Index structure
    index_data = {
        'source_file': source_filename,
        'controller': controller_name,
        'processor_type': processor_type,
        'software_revision': root.get('SoftwareRevision', ''),
        'export_date': root.get('ExportDate', ''),
        'generated': datetime.now(timezone.utc).isoformat(),
        'programs': [],
        'aois': [],
        'jsr_calls': {},
    }

    xref = {}
    routine_count = 0

    # ------- Programs -------
    programs_elem = controller_elem.find('.//Programs')
    if programs_elem is not None:
        for prog_el in programs_elem.findall('Program'):
            prog_name = prog_el.get('Name', '')
            main_routine = prog_el.get('MainRoutineName', '')
            prog_info = {
                'name': prog_name,
                'main_routine': main_routine,
                'disabled': prog_el.get('Disabled', 'false') == 'true',
                'description': get_description(prog_el),
                'routines': [],
            }

            routines_elem = prog_el.find('Routines')
            if routines_elem is None:
                index_data['programs'].append(prog_info)
                continue

            for rtn_el in routines_elem.findall('Routine'):
                rtn_name = rtn_el.get('Name', '')
                rtn_type = rtn_el.get('Type', 'RLL')

                filename = f'{sanitize_filename(prog_name)}--{sanitize_filename(rtn_name)}.xml'
                filepath = out_dir / filename

                all_tag_refs = set()
                jsr_targets = []

                if rtn_type == 'RLL':
                    for rung_el in rtn_el.findall('.//RLLContent/Rung'):
                        text_el = rung_el.find('Text')
                        rung_text = text_el.text.strip() if text_el is not None and text_el.text else ''
                        rung_num = int(rung_el.get('Number', 0))

                        all_tag_refs.update(extract_tag_refs(rung_text))
                        jsr_targets.extend(extract_jsr_targets(rung_text))
                        process_rung_xref(rung_text, rung_num, filename,
                                          prog_name, rtn_name, tag_index, xref)

                elif rtn_type == 'ST':
                    st_content = rtn_el.find('.//STContent')
                    if st_content is not None:
                        for child in st_content.iter():
                            if child.text:
                                all_tag_refs.update(extract_tag_refs(child.text))

                write_routine_xml(
                    filepath, rtn_el,
                    source_file=source_filename,
                    controller=controller_name,
                    program=prog_name,
                    main_routine=main_routine,
                    tag_refs=all_tag_refs,
                    tag_index=tag_index,
                    prog_name=prog_name,
                )

                if jsr_targets:
                    target_files = [
                        f'{sanitize_filename(prog_name)}--{sanitize_filename(t)}.xml'
                        for t in jsr_targets
                    ]
                    # Deduplicate while preserving order
                    seen = set()
                    deduped = []
                    for tf in target_files:
                        if tf not in seen:
                            seen.add(tf)
                            deduped.append(tf)
                    index_data['jsr_calls'][filename] = deduped

                rung_count = len(rtn_el.findall('.//Rung')) if rtn_type == 'RLL' else 0
                prog_info['routines'].append({
                    'name': rtn_name,
                    'type': rtn_type,
                    'file': filename,
                    'rung_count': rung_count,
                    'is_main': rtn_name == main_routine,
                    'tag_refs_count': len(all_tag_refs),
                })
                routine_count += 1

            index_data['programs'].append(prog_info)

    # ------- AOIs -------
    aoi_defs = controller_elem.find('.//AddOnInstructionDefinitions')
    if aoi_defs is not None:
        for aoi_el in aoi_defs.findall('AddOnInstructionDefinition'):
            aoi_name = aoi_el.get('Name', '')
            aoi_info = {
                'name': aoi_name,
                'description': get_description(aoi_el),
                'revision': aoi_el.get('Revision', ''),
                'routines': [],
            }

            for rtn_el in aoi_el.findall('.//Routines/Routine'):
                rtn_name = rtn_el.get('Name', '')
                rtn_type = rtn_el.get('Type', 'RLL')

                filename = f'AOI--{sanitize_filename(aoi_name)}--{sanitize_filename(rtn_name)}.xml'
                filepath = out_dir / filename

                all_tag_refs = set()
                if rtn_type == 'RLL':
                    for rung_el in rtn_el.findall('.//RLLContent/Rung'):
                        text_el = rung_el.find('Text')
                        rung_text = text_el.text.strip() if text_el is not None and text_el.text else ''
                        all_tag_refs.update(extract_tag_refs(rung_text))

                write_routine_xml(
                    filepath, rtn_el,
                    source_file=source_filename,
                    controller=controller_name,
                    program=f'AOI:{aoi_name}',
                    main_routine='',
                    tag_refs=all_tag_refs,
                    tag_index=tag_index,
                    prog_name=f'AOI:{aoi_name}',
                )

                rung_count = len(rtn_el.findall('.//Rung')) if rtn_type == 'RLL' else 0
                aoi_info['routines'].append({
                    'name': rtn_name,
                    'type': rtn_type,
                    'file': filename,
                    'rung_count': rung_count,
                })
                routine_count += 1

            index_data['aois'].append(aoi_info)

    # ------- Write _index.json -------
    with open(out_dir / '_index.json', 'w', encoding='utf-8') as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)

    # ------- Write _tags.csv -------
    with open(out_dir / '_tags.csv', 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Name', 'DataType', 'Scope', 'Description', 'AliasFor',
            'ExternalAccess', 'Class', 'Constant', 'Dimensions',
        ])
        for (_scope, _name), info in sorted(tag_index.items()):
            writer.writerow([
                info['name'], info['data_type'], info['scope'],
                info['description'], info['alias_for'],
                info['external_access'], info['tag_class'],
                info['constant'], info['dimensions'],
            ])

    # ------- Write _cross_references.json -------
    sorted_xref = dict(sorted(xref.items()))
    xref_output = {
        'source_file': source_filename,
        'controller': controller_name,
        'generated': datetime.now(timezone.utc).isoformat(),
        'tag_count': len(sorted_xref),
        'tags': sorted_xref,
    }
    with open(out_dir / '_cross_references.json', 'w', encoding='utf-8') as f:
        json.dump(xref_output, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f'  Output:    {out_dir}')
        print(f'  Routines:  {routine_count}')
        print(f'  Tags:      {len(tag_index)}')
        print(f'  Xref tags: {len(xref)}')
    else:
        print(f'  {routine_count} routines -> {out_dir}')


def main():
    parser = argparse.ArgumentParser(
        description='Split L5X files into individual routine files with '
                    'index, tag CSV, and cross-references.',
    )
    parser.add_argument('path',
                        help='Path to an L5X file or directory with L5X files')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    args = parser.parse_args()

    target = Path(args.path)

    if target.is_file() and target.suffix.lower() == '.l5x':
        process_l5x(target, verbose=args.verbose)
    elif target.is_dir():
        l5x_files = list(target.rglob('*.l5x')) + list(target.rglob('*.L5X'))
        seen = set()
        unique = []
        for f in l5x_files:
            k = str(f).lower()
            if k not in seen:
                seen.add(k)
                unique.append(f)
        if not unique:
            print(f'No L5X files found in {target}')
            sys.exit(1)
        print(f'Found {len(unique)} L5X file(s)')
        for f in unique:
            process_l5x(f, verbose=args.verbose)
    else:
        print(f'Error: {target} is not an L5X file or directory')
        sys.exit(1)

    print('Done.')


if __name__ == '__main__':
    main()
