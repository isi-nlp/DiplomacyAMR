#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Written by Ulf Hermjakob, USC/ISI
"""

import argparse
from collections import defaultdict
from daide import Daide
import json
import os
from pathlib import Path
import re
import regex
import sys
from typing import Optional, Tuple, Union

data_dir = Path(__file__).parent.parent / 'data'
data_dir_path = str(data_dir.resolve())


def slot_value_in_double_colon_del_list(line: str, slot: str, default: Optional = None) -> str:
    """For a given slot, e.g. 'cost', get its value from a line such as '::s1 of course ::s2 ::cost 0.3' -> 0.3
    The value can be an empty string, as for ::s2 in the example above."""
    m = re.match(fr'(?:.*\s)?::{slot}(|\s+\S.*?)(?:\s+::\S.*|\s*)$', line)
    return m.group(1).strip() if m else default


def has_matching_outer_parentheses(s: str) -> bool:
    if not s.startswith('('):
        return False
    elif not s.endswith(')'):
        return False
    n_open_parentheses = 0
    for i, c in enumerate(s):
        if c == '(':
            n_open_parentheses += 1
        elif c == ')':
            n_open_parentheses -= 1
        if n_open_parentheses <= 0 and i < len(s)-1:
            return False
    return n_open_parentheses == 0


class AMRnode:
    def __init__(self, concept: str, parent=None, variable: Optional = None):
        self.concept = concept
        self.variable = variable
        self.parent = parent
        self.subs: list[Tuple[str, Union[AMRnode, str, None]]] = []  # role sub
        self.parents: list[AMRnode] = []


class AMR:
    def __init__(self):
        self.root: Optional[AMRnode] = None
        self.variable_to_amr_node = {}
        self.orphan_variables = defaultdict(list)
        self.previously_printed_variables = []

    def match_map(self, amr_node, d: dict, s: str):
        while m3 := re.match(r'(.*?)\$([a-z][a-z0-9]*)(?![a-z0-9])(.*)$', s):
            pre, var, post = m3.group(1, 2, 3)
            value = d.get(var)
            if value is None:
                value = '$' + var
            elif ' ' in value \
                    and (not (has_matching_outer_parentheses(value))) \
                    and (not (pre.endswith('(') and post.startswith(')'))):
                value = '(' + value + ')'
            s = pre + value + post
        if self.sub_amr_node_by_role(amr_node, ['polarity']) == '-':
            s = f'NOT ({s})'
        while m3 := re.match(r'(.*)\((\([^()]*\))\)(.*)$', s):
            s = m3.group(1) + m3.group(2) + m3.group(3)
        return s

    def string_to_amr(self, s: str, parent: Optional[AMRnode] = None, rec_level: int = 0) -> \
            Tuple[Optional[AMRnode], str, list[str], Optional[str], Optional[str], Optional[str]]:
        # AMR_Node built, rest, error message, sentence_id, sentence
        errors = []
        snt = None
        snt_id = None
        amr_s = None
        while m2 := re.match(r'\s*(#[^\n]*)\n(.*)', s, re.DOTALL):
            comment_line = m2.group(1).strip()
            s = m2.group(2)
            if snt_cand := slot_value_in_double_colon_del_list(comment_line, 'snt'):
                snt = snt_cand
            elif snt_id_cand := slot_value_in_double_colon_del_list(comment_line, 'id'):
                snt_id = snt_id_cand
        # indent = ' '*4*rec_level
        if snt_id and (m1 := re.match(r'(\(.*?\n(?:[ \t]+.*\S\s*?\n)*)', s)):
            amr_s = m1.group(1)
        if m3 := re.match(r'\s*\(([a-z]\d*)\s*/\s*([a-z][a-z0-9]*(?:-[a-z0-9]+)*)(.*)', s, re.DOTALL):
            variable, concept, s = m3.group(1, 2, 3)
            amr_node = AMRnode(concept, parent=parent, variable=variable)
            self.variable_to_amr_node[variable] = amr_node
            # print(f"{indent}New AMR node: ({variable} / {concept})")
            if self.root is None:
                self.root = amr_node
            while m_role := re.match(r'\s*:([a-z][a-z0-9]*(?:-[a-z0-9]+)*)(.*)', s, re.DOTALL | re.IGNORECASE):
                role, s = m_role.group(1, 2)
                # sub is AMR
                if re.match(r'\s*\(', s, re.DOTALL):
                    sub_amr, s, sub_errors, _snt_id, _snt, _amr_s = self.string_to_amr(s, rec_level=rec_level+1)
                    errors.extend(sub_errors)
                    if sub_amr:
                        amr_node.subs.append((role, sub_amr))
                        sub_amr.parents.append(amr_node)
                        # print(f"{indent}New AMR sub1: :{role} {sub_amr.variable}/{sub_amr.concept}")
                    else:
                        errors.append(f'Unexpected non-AMR: {s}')
                        return amr_node, s, errors, snt_id, snt, amr_s
                # sub is quoated string
                elif m_string := re.match(r'\s*"((?:\\"|[^"]+)*)"(.*)', s, re.DOTALL):
                    quoted_string_value, s = m_string.group(1, 2)
                    amr_node.subs.append((role, quoted_string_value))
                    # print(f'{indent}New AMR sub2: :{role} "{quoted_string_value}"')
                # sub is reentrancy variable
                elif m_string := re.match(r'\s*([a-z]\d*)(?![a-z])(.*)', s, re.DOTALL):
                    ref_variable, s = m_string.group(1, 2)
                    if ref_amr := self.variable_to_amr_node.get(ref_variable):
                        amr_node.subs.append((role, ref_amr))
                        # print(f'{indent}New AMR sub3: :{role} {ref_variable}')
                    else:
                        self.orphan_variables[ref_variable].append((amr_node, len(amr_node.subs)))
                        amr_node.subs.append((role, None))
                # sub is non-quoted string
                elif m_string := re.match(r'\s*([^\s()]+)(.*)', s, re.DOTALL):
                    unquoted_string_value, s = m_string.group(1, 2)
                    amr_node.subs.append((role, unquoted_string_value))
                    # print(f'{indent}New AMR sub4: :{role} {unquoted_string_value}')
                else:
                    errors.append(f'Unexpected :{role} arg: {s}')
                    return amr_node, s, errors, snt_id, snt, amr_s
            if m_rest := re.match(r'\s*\)(.*)', s, re.DOTALL):
                s = m_rest.group(1)
            else:
                errors.append(f'Inserting missing ) at: {snt_id or s}')
            if rec_level == 0:
                for ref_variable in self.orphan_variables.keys():
                    if ref_amr_node := self.variable_to_amr_node.get(ref_variable):
                        for orphan_location in self.orphan_variables[ref_variable]:
                            parent_amr_node, child_index = orphan_location
                            role = parent_amr_node.subs[child_index][0]
                            parent_amr_node.subs[child_index] = (role, ref_amr_node)
                    else:
                        errors.append(f"Error: For {snt_id}, can't resolve orphan reference {ref_variable}")
            return amr_node, s, errors, snt_id, snt, amr_s
        else:
            return None, "", errors, snt_id, snt, amr_s

    def amr_to_string(self, amr_node: AMRnode = None, rec_level: int = 0, no_indent: bool = False) -> str:
        if amr_node is None:
            amr_node = self.root
            self.previously_printed_variables = []
        indent = ' '*6*(rec_level+1)
        concept = amr_node.concept
        variable = amr_node.variable
        result = f"({variable} / {concept}"
        for role, sub in amr_node.subs:
            if role == "name" and isinstance(sub, AMRnode) and sub.concept == "name":
                no_indent = True
            if no_indent:
                result += f" :{role} "
            else:
                result += f"\n{indent}:{role} "
            if isinstance(sub, AMRnode):
                if sub.variable in self.previously_printed_variables:
                    result += sub.variable
                else:
                    result += self.amr_to_string(amr_node=sub, rec_level=rec_level+1, no_indent=no_indent)
                    self.previously_printed_variables.append(sub.variable)
            elif isinstance(sub, str):
                result += f'"{sub}"'
            # elif isinstance(sub, int)
        result += ')'
        return result

    @staticmethod
    def sub_amr_node_by_role(amr_node, roles) -> Optional[Union[AMRnode, str]]:
        for role, sub in amr_node.subs:
            if role in roles:
                return sub
        return None

    @staticmethod
    def parents(amr_node) -> list[AMRnode]:
        return amr_node.parents

    def ancestor_is_in_concepts(self, amr_node, concepts: list[str],
                                visited_amr_nodes: Optional[list[AMRnode]] = None) -> bool:
        # Avoid loops
        if visited_amr_nodes and amr_node in visited_amr_nodes:
            return False
        if visited_amr_nodes is None:
            visited_amr_nodes = []
        for parent in self.parents(amr_node):
            if parent.concept in concepts:
                return True
            visited_amr_nodes.append(amr_node)
            if self.ancestor_is_in_concepts(parent, concepts, visited_amr_nodes):
                return True
        return False

    def ne_amr_to_name(self, amr_node) -> str:
        if isinstance(amr_node, AMRnode) and amr_node.concept in ['country', 'province', 'sea']:
            if (name_amr_node := self.sub_amr_node_by_role(amr_node, ['name'])) \
                    and name_amr_node.concept == 'name':
                name_elements = []
                i = 1
                while op := self.sub_amr_node_by_role(name_amr_node, [f"op{i}"]):
                    name_elements.append(op)
                    i += 1
                return ' '.join(name_elements)
        return ''

    def match_for_daide(self, amr_node: AMRnode, target_s: str, in_dict: Optional[dict] = None) -> Optional[dict]:
        if m2 := re.match(r'\((\S+)\s+(.*)\)$', target_s):
            result = in_dict or {'match': True}
            concept = amr_node.concept
            instance_s = m2.group(1)
            if instance_s == concept:
                pass
            elif ((m2b := re.match(r'\$([a-z][a-z0-9]*)\((.*)\)$', instance_s))
                    and (concept in m2b.group(2).split('|'))):
                result[m2b.group(1)] = daide.name_to_id.get(concept) or concept
            elif m1 := re.match(r'\$([a-z][a-z0-9]*)$', instance_s):
                result[m1.group(1)] = daide.name_to_id.get(concept) or concept
            else:
                return None
            for arg_value in regex.findall(r':([a-z][-a-z0-9]*)\s+([^\s()]+|(\((?:[^()]++|(?3))*\))(?:\([^\s()]+\))?)',
                                           m2.group(2), re.IGNORECASE):
                arg, value = arg_value[0], arg_value[1]
                # print(f'  arg: {arg}  value: {value}')
                if sub_amr_node := self.sub_amr_node_by_role(amr_node, [arg]):
                    sub_concept = sub_amr_node.concept
                    # print(f'    sub_concept: {sub_concept}')
                    if value == sub_concept:
                        pass
                    elif ((m2c := (re.match(r'\$([a-z][a-z0-9]*)\((.*)\)$', value)
                                   or re.match(r'\$([a-z][a-z0-9]*)$', value)))
                            and ((m2c.lastindex == 1) or (sub_concept in m2c.group(2).split('|')))):
                        var = m2c.group(1)
                        if sub_name := self.ne_amr_to_name(sub_amr_node):
                            result[var] = daide.name_to_id.get(sub_name) or sub_name
                        elif sub_amr_node.subs:
                            result[var] = self.amr_to_daide(sub_amr_node) or sub_concept
                        else:
                            result[var] = daide.name_to_id.get(sub_concept) or sub_concept
                    elif has_matching_outer_parentheses(value):
                        if self.match_for_daide(sub_amr_node, value, result) is None:
                            return None
                    else:
                        return None
                else:
                    return None
            return result
        return None

    def amr_to_daide(self, amr_node: AMRnode = None) -> str:
        if amr_node is None:
            amr_node = self.root
        if (entity_name := self.ne_amr_to_name(amr_node)) \
                and (daide_id := daide.name_to_id.get(entity_name)):
            return daide_id
        concept = amr_node.concept
        if concept == 'and':
            daide_elements = []
            i = 1
            while op_amr_node := self.sub_amr_node_by_role(amr_node, [f"op{i}"]):
                if daide_element := self.amr_to_daide(op_amr_node):
                    if ' ' in daide_element and not has_matching_outer_parentheses(daide_element):
                        daide_element = '(' + daide_element + ')'
                    daide_elements.append(daide_element)
                    i += 1
            return ' '.join(daide_elements)
        if d := self.match_for_daide(amr_node,
                                     '($utype(army|fleet) :mod $power(country) :location $location(sea|province))'):
            return self.match_map(amr_node, d, '($power $utype $location)')
        if d := self.match_for_daide(amr_node, '(move-01 :ARG1 $unit :ARG2 $destination)'):
            return self.match_map(amr_node, d, '$unit MTO $destination')
        if d := self.match_for_daide(amr_node, '(coast :location ($compass(north|east|south|west)'
                                               ' :part-of $province(province)))'):
            return self.match_map(amr_node, d, '($province $compass)')
        if d := self.match_for_daide(amr_node, '(hold-03 :ARG1 $unit)'):
            return self.match_map(amr_node, d, '$unit HLD')
        if d := self.match_for_daide(amr_node, '(support-01 :ARG0 $supporter :ARG1 $supportee)'):
            return self.match_map(amr_node, d, '$supporter SUP $supportee')
        if d := self.match_for_daide(amr_node, '(ally-01 :ARG1 $allies :ARG3 $ennemies)'):
            return self.match_map(amr_node, d, 'ALY ($allies) VSS ($ennemies)')
        if d := self.match_for_daide(amr_node, '(ally-01 :ARG1 $allies)'):
            return self.match_map(amr_node, d, 'ALY ($allies)')
        if d := self.match_for_daide(amr_node, '(submit-01 :ARG1 $submission)'):
            return self.match_map(amr_node, d, 'SUB $submission')
        if d := self.match_for_daide(amr_node, '(propose-01 :ARG1 $proposal)'):
            return self.match_map(amr_node, d, 'PRP ($proposal)')
        if d := self.match_for_daide(amr_node, '(build-01 :ARG0 $power(country) :ARG1 $utype(army|fleet) '
                                               ':location $location(province))'):
            return self.match_map(amr_node, d, '($power $utype $location) BLD')
        if d := self.match_for_daide(amr_node, '(agree-01 :ARG1 $proposal)'):
            return self.match_map(amr_node, d, 'YES ($proposal)')
        if d := self.match_for_daide(amr_node, '(reject-01 :ARG1 $proposal)'):
            return self.match_map(amr_node, d, 'REJ ($proposal)')
        if d := self.match_for_daide(amr_node, '(demilitarize-01 :ARG1 $powers :ARG2 $locations)'):
            return self.match_map(amr_node, d, 'DMZ ($powers) ($locations)')
        if d := self.match_for_daide(amr_node, '(remove-01 :ARG1 $unit(army|fleet))'):
            return self.match_map(amr_node, d, '$unit REM')
        if d := self.match_for_daide(amr_node, '(transport-01 :ARG1 $army(army) :ARG3 $destination(province) '
                                               ':ARG4 $path(sea))'):
            return self.match_map(amr_node, d, '$army CTO $destination VIA $path')
        if d := self.match_for_daide(amr_node, '(transport-01 :ARG0 $fleet(fleet) :ARG1 $army(army) '
                                               ':ARG3 $destination(province))'):
            return self.match_map(amr_node, d, '$fleet CVY $army CTO $destination')
        if d := self.match_for_daide(amr_node, '(retreat-01 :ARG1 $unit(army|fleet) '
                                               ':destination $destination(province|sea))'):
            return self.match_map(amr_node, d, '$unit RTO $destination')
        if (d := self.match_for_daide(amr_node, '(have-03 :ARG0 $owner(country) :ARG1 $province(province))')) \
                and self.ancestor_is_in_concepts(amr_node, ['propose-01', 'agree-01']):
            return self.match_map(amr_node, d, 'SCD ($owner $province)')
        if d := self.match_for_daide(amr_node, '(peace :op1 $c1(country) :op2 $c2(country) :op3 $c3(country))'):
            return self.match_map(amr_node, d, 'PCE ($c1 $c2 $c3)')
        if d := self.match_for_daide(amr_node, '(peace :op1 $c1(country) :op2 $c2(country))'):
            return self.match_map(amr_node, d, 'PCE ($c1 $c2)')
        result = f'({concept}'
        for role, sub in amr_node.subs:
            result += f" :{role} "
            if isinstance(sub, AMRnode):
                result += self.amr_to_daide(amr_node=sub)
            elif isinstance(sub, str):
                result += f'"{sub}"'
        result += ')'
        return result

    @staticmethod
    def file_to_amrs(filename: str, max_n: Optional[int]) -> Tuple[list, list, list, list, list]:
        s = ""
        with open(filename) as f:
            s += f.read()
        n_amrs = 0
        amr_roots = []
        snt_ids = []
        snts = []
        errors = []
        amr_strings = []
        # print("AMR in:", s)
        while re.match(r'\s*\S', s):
            orig_s = s
            amr = AMR()
            amr_node, s, error_list, snt_id, snt, amr_s = amr.string_to_amr(s)
            if amr_node:
                amr.root = amr_node
                amr_roots.append(amr)
                snt_ids.append(snt_id)
                snts.append(snt)
                errors.append(error_list)
                amr_strings.append(amr_s)
                n_amrs += 1
            else:
                print(f'Break at\n{orig_s[0:500]}')
                print(f'{0/0}')
                break
            if max_n is not None and n_amrs >= max_n:
                break
        return amr_roots, snt_ids, snts, errors, amr_strings


daide = Daide(os.path.join(data_dir_path, 'diplomacy-resources.txt'))
extended_amr_concepts1 = ['attack-01', 'betray-01', 'defend-01', 'dislodge-01', 'expect-01', 'fear-01',
                          'gain-02', 'lie-08', 'lose-02', 'possible-01', 'prevent-01', 'threaten-01',
                          'trust-01', 'warn-01']


def main_test():
    amr = AMR()
    amr_s = '(a / army :mod (c / country :name (n / name :op1 "Italy")) ' \
            ':location (p / province :name (n2 / name :op1 "Burgundy")))'
    print(amr_s)
    target_s = "($unit(army|fleet) :mod $power(country) :location $loc(province|sea))"
    print(target_s)
    amr_tuple = amr.string_to_amr(amr_s)
    amr_node = amr_tuple[0]
    result = amr.match_for_daide(amr_node, target_s)
    print(result)


def main():
    parser = argparse.ArgumentParser(description='Analyzes a given text for a wide range of anomalies')
    parser.add_argument('-i', '--input', type=Path,
                        default=sys.stdin, metavar='AMR-INPUT-FILENAME', help='(default: STDIN)')
    parser.add_argument('-o', '--output', type=argparse.FileType('w', encoding='utf-8', errors='ignore'),
                        default=sys.stdout, metavar='OUTPUT-FILENAME', help='(default: STDOUT)')
    parser.add_argument('-j', '--json', type=argparse.FileType('w', encoding='utf-8', errors='ignore'),
                        default=None, metavar='JSONL-OUTPUT-FILENAME', help='(default: None)')
    parser.add_argument('-m', '--max', type=int, default=None, help='(maximum number of AMRs in ouput)')
    parser.add_argument('-d', '--developer_mode', action='count', default=0)
    parser.add_argument('-v', '--verbose', action='count', default=0, help='write change log etc. to STDERR')
    args = parser.parse_args()
    n_amrs = 0
    n_amr_empty = 0
    n_amr_with_extended_concept1 = 0
    n_amr_with_extended_concept2 = 0
    n_underspecified_unit = 0
    n_daide_without_problem = 0
    extended_concept_counter1 = defaultdict(int)
    extended_concept_counter2 = defaultdict(int)
    snt_ids_with_recursion_error = []
    amrs, snt_ids, snts, errors, amr_strings \
        = AMR.file_to_amrs(args.input, args.max)
    out = args.output
    for amr, snt_id, snt, error_list, amr_s in zip(amrs, snt_ids, snts, errors, amr_strings):
        n_amrs += 1
        daide_problematic = False
        show_daide_in_dev_mode = True
        try:
            amr_s2 = amr.amr_to_string()
        except RecursionError:
            snt_ids_with_recursion_error.append(snt_id)
            print(f'RecursionError for {snt_id}')
            continue
        if amr_s2 == '(a / amr-empty)':
            n_amr_empty += 1
            show_daide_in_dev_mode = False
            daide_s = ''
        else:
            daide_s = amr.amr_to_daide()
            if extended_amr_concepts := re.findall(r'([a-z]\S*-\d\d\b)', daide_s):
                if set(extended_amr_concepts1) & set(extended_amr_concepts):
                    n_amr_with_extended_concept1 += 1
                    for extended_amr_concept in extended_amr_concepts:
                        if extended_amr_concept in extended_amr_concepts1:
                            extended_concept_counter1[extended_amr_concept] += 1
                    show_daide_in_dev_mode = False
                else:
                    n_amr_with_extended_concept2 += 1
                    for extended_amr_concept in extended_amr_concepts:
                        extended_concept_counter2[extended_amr_concept] += 1
                daide_problematic = True
            if '(unit ' in daide_s \
                    or re.search(r'\((?:army|fleet) :(?:mod|location) [A-Z]{3}\)', daide_s):
                n_underspecified_unit += 1
                daide_problematic = True
                show_daide_in_dev_mode = False
            if re.search('[a-z]', daide_s):
                daide_problematic = True
        if regex.search(r'[A-Z]{3}', daide_s):
            if regex.search(r'[a-z]', daide_s):
                daide_status = 'Partial-DAIDE'
            else:
                daide_status = 'Full-DAIDE'
        else:
            daide_status = 'No-DAIDE'
        if ((not args.developer_mode) or show_daide_in_dev_mode) and not (args.json and args.output == sys.stdout):
            out.write(f'# ::id {snt_id}\n')
            out.write(f'# ::snt {snt}\n')
            for error in error_list:
                out.write(f'# ::error {error}\n')
            out.write(f'AMR:\n{amr_s.strip()}\n')
            # out.write(f'AMR string (r): {amr_s2.strip()}\n')
            if daide_status == 'Full-DAIDE':
                out.write(f'DAIDE: {daide_s}\n')
            elif daide_status == 'Partial-DAIDE':
                out.write(f'PARTIAL-DAIDE: {daide_s}\n')
            else:
                out.write('NO-DAIDE\n')
            out.write('\n')
        if args.json:
            d = {'id': snt_id, 'snt': snt, 'amr': amr_s.strip(), 'daide-status': daide_status}
            if daide_s:
                d['daide'] = daide_s
            args.json.write(json.dumps(d) + "\n")
        if not daide_problematic:
            n_daide_without_problem += 1
    if args.developer_mode:
        out.write(f'Summary: {n_amrs} AMRs; {n_amr_empty} empty AMRs; {n_daide_without_problem} unproblematic; '
                  f'{n_underspecified_unit} underspecified units; '
                  f'{n_amr_with_extended_concept1}/{n_amr_with_extended_concept2} AMRs with extended concept\n')
        out.write(f'Last snt-id: {snt_ids[-1]}')
        if snt_ids_with_recursion_error:
            sys.stderr.write(f'Recursion errors for {snt_ids_with_recursion_error}\n')
        for extended_concept in sorted(extended_concept_counter1.keys()):
            sys.stderr.write(f'  Extended concept {extended_concept} ({extended_concept_counter1[extended_concept]})\n')
        sys.stderr.write('\n')
        for extended_concept in sorted(extended_concept_counter2.keys()):
            sys.stderr.write(f'  Extended concept {extended_concept} ({extended_concept_counter2[extended_concept]})\n')


if __name__ == "__main__":
    main()
