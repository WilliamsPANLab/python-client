"""Flywheel Demographic report for a Flywheel project.

Usage:
  demographic_report.py GROUP PROJECT

Options:
  -h --help     Show this screen.
"""
from docopt import docopt
from scitran_client import ScitranClient, query, Projects, Acquisitions, Groups
import re
import math


def _subject_code(subject):
    if 'test' in subject['code']:
        # we don't try to parse test entries
        return subject['code']
    match = re.match(r'\w{2}\d{5}', subject['code'])
    assert match, 'Could not find code for {}'.format(subject['code'])
    # upper() is a good idea to get to a canonical ID
    return match.group(0).upper()


def _session_id(session):
    # UID is supplied by the scanner and label is added by
    # the researcher. we prefer UID and require at least one
    # of the two
    if 'uid' in session:
        return session['uid']
    elif 'label' in session:
        return session['label']
    else:
        raise Exception('missing uid and label keys in {}'.format(session))


def report(group, project):
    client = ScitranClient()
    # querying for acquisitions first since we have to fetch for them anyway.
    results = client.search(query(Acquisitions).filter(
        Projects.label.match(project),
        Groups.name.match(group),
    ))

    assert results, 'Could not find results for project {} for group {}.'.format(project, group)

    acquisitions_by_session = {}
    for result in results:
        session = result['_source']['session']
        acquisitions_by_session.setdefault(
            _session_id(session), []).append(result)

    # indexing sessions by label to get a unique list of sessions
    sessions_by_id = {
        _session_id(session): session
        for session in (
            result['_source']['session']
            for result in results
        )
    }

    # indexing subjects by code to get a unique list of subjects
    subjects_by_code = {
        _subject_code(session['subject']): session['subject']
        for session in sessions_by_id.values()
    }

    sessions_by_subject = {}
    for session in sessions_by_id.values():
        sessions_by_subject.setdefault(
            _subject_code(session['subject']), []).append(session)

    def _seconds_to_years(seconds):
        return int(math.floor(float(seconds) / 60 / 60 / 24 / 365))

    def _report_by_sex(subjects, sex):
        subjects = [
            subject for subject in subjects
            if subject.get('sex') == sex
        ]
        ages = [s['age'] for s in subjects]
        return '{} {}s between ages of {} and {}'.format(
            len(subjects),
            sex,
            _seconds_to_years(min(ages)),
            _seconds_to_years(max(ages)),
        )

    subjects = subjects_by_code.values()

    missing_t1w = [
        subject_code
        for subject_code in subjects_by_code.keys()
        if not any(
            acquisition['_source']['label'] == 'T1w 1mm'
            for session in sessions_by_subject[subject_code]
            for acquisition in acquisitions_by_session[_session_id(session)]
        )
    ]

    print '''{}: {}
Total # of subjects: {}
{}
{}
{} subjects with unspecified sex
{} missing T1w 1mm: {}
'''.format(
        group, project,
        len(subjects_by_code),
        _report_by_sex(subjects, 'male'),
        _report_by_sex(subjects, 'female'),
        len([s for s in subjects if s.get('sex') is None]),
        len(missing_t1w), ', '.join(missing_t1w),
    )


if __name__ == '__main__':
    arguments = docopt(__doc__, version='Flywheel Demographic Report 1.0')
    report(arguments['GROUP'], arguments['PROJECT'])
