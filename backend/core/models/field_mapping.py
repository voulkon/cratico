field_map = {
    "Organization": {
        "latinName": "latin_name",
        "vatNumber": "vat_number",
        "fekNumber": "fek_number",
        "fekIssue": "fek_issue",
        "fekYear": "fek_year",
        "supervisorOrgUid": "supervisor_org_uid",
        "supervisorOrgName": "supervisor_org_name",
        "organizationDomains": "domains",  # note: this maps to related_name="domains" on OrganizationDomain
    },
    "Unit": {
        "activeFrom": "active_from",
        "activeUntil": "active_until",
        "unitDomains": "domains",  # maps to related_name="domains" on UnitDomain
        "parentId": "parent",  # ForeignKey to self
    },
    "Signer": {
        "firstName": "first_name",
        "lastName": "last_name",
        "activeFrom": "active_from",
        "activeUntil": "active_until",
        "organizationId": "organization",  # ForeignKey
        "hasOrganizationSignRights": "has_organization_sign_rights",
    },
    "SignerUnit": {
        "uid": "unit",  # actually maps to a ForeignKey to Unit by uid
        "positionId": "position",  # maps to ForeignKey to Position by uid
        "positionLabel": "position_label",  # nested label
    },
    "Position": {
        # All fields match, so nothing to include
    },
    "Dictionary": {
        # All fields match
    },
    "DictionaryItem": {
        "parent": "parent",  # still include it because in Django it's a ForeignKey
        "dictionary": "dictionary",
    },
    "DictionaryValuesResponse": {
        "name": "uid",  # `name` in API corresponds to dictionary UID
        "items": "items",  # matches related_name on Dictionary
    },
    "DictionaryListItem": {
        # All fields match
    },
    "DictionariesListResponse": {
        "dictionaries": "dictionaries",  # wrapper field, not in models
    },
    "Types": {},
    "TypeSummary": {
        "allowedInDecisions": "allowed_in_decisions",
    },
    "TypeDetails": {
        "allowedInDecisions": "allowed_in_decisions",
        "extraFields": "extra_fields",  # maps to related_name on ExtraField model
    },
    "ExtraField": {
        "type": "field_type",
        "maxLength": "max_length",
        "searchTerm": "search_term",
        "relAdaDecisionTypes": "rel_ada_decision_types",
        "relAdaConstrainedInOrganization": "rel_ada_constrained_in_organization",
        "fixedValueList": "fixed_value_list",
        "nestedFields": "nested_fields",  # maps to related_name on self-reference
    },
}
