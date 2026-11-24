from .adapters import REGISTRY


RECORD_LABELS = {
    'income_certificate': 'Income certificate',
    'residence_certificate': 'Residence certificate',
    'household_certificate': 'Household record',
}
REVIEW_LABELS = {
    'Education Officers': 'Education department',
    'Welfare Officers': 'Welfare department',
    'Municipal Reviewers': 'Municipality',
}
REQUEST_STATUSES = {
    'awaiting_consent': 'Sharing permission needed',
    'processing': 'Collecting records',
    'exchange_failed': 'Records could not be collected',
    'review': 'Waiting for department review',
    'approved': 'Approved',
    'rejected': 'Rejected',
    'withdrawn': 'Withdrawn',
}
DEMO_DESCRIPTIONS = {
    'student-scholarship': 'Apply for a student scholarship using your existing income certificate.',
    'housing-assistance': 'Apply for housing assistance using your existing income, residence and household records.',
}


def describe_service(service):
    if service.description == 'Local departmental service using reviewed identity links and consent. Seed records are fictional.':
        return DEMO_DESCRIPTIONS.get(service.code, service.description)
    return service.description


def describe_steps(workflow):
    for step in workflow:
        if step['kind'] == 'fetch':
            adapter = REGISTRY[step['connector']]
            department = adapter.department
            yield {
                **step,
                'label': RECORD_LABELS.get(step['scope'], step['scope'].replace('_', ' ').capitalize()),
                'department': department,
                'source': {'revenue': 'Revenue department', 'municipality': 'Municipality'}.get(department, department.title()),
                'source_format': adapter.format.upper(),
            }
        else:
            yield {**step, 'label': REVIEW_LABELS.get(step['role'], step['role'])}
