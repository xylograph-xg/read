"""Machine-readable completion of reader stages, independent of warning prose."""
METADATA_STAGES=('paper_info','key_findings','introduction','conclusion')
GENERATION_SCHEMA_VERSION=2


def metadata_complete(meta):
    stages=meta.get('generation',{}).get('stages',{})
    return all(stages.get(name,{}).get('state')=='ok' for name in METADATA_STAGES)


def generation_complete(card):
    meta=card.get('meta',{})
    if meta.get('science_checks',{}).get('blocking'):return False
    if meta.get('metadata_generation_ok') is not True or not metadata_complete(meta):return False
    figures=card.get('figures',[]);equations=card.get('equations',[])
    schema=meta.get('generation',{}).get('schema_version',1)
    if meta.get('reading_contract_version',0)>=10 and schema!=GENERATION_SCHEMA_VERSION:return False
    if any(r.get('truncated_fields') for r in meta.get('input_budget_scope',[])):return False
    if any(r.get('truncated') for rows in meta.get('prompt_input_scope',{}).values() for r in rows):return False
    if schema>=2:
        if any(i.get('evidence_status')!='verified' or not i.get('evidence_quote') for i in figures+equations):return False
        if equations and sum(not e.get('latex') for e in equations)/len(equations)>.25:return False
        if meta.get('generation_diagnostics',{}).get('automatic_retry_blocked'):return False
    if not figures and not equations:return False
    coverage=meta.get('evidence_coverage',{})
    if coverage:
        if coverage.get('figures')!=len(figures) or coverage.get('equations')!=len(equations):return False
        if coverage.get('truncated') or coverage.get('unresolved'):return False
    paths=[item.get('image_path') for item in figures+equations]
    if any(not path for path in paths) or len(paths)!=len(set(paths)):return False
    return (all(x.get('status')=='ok' and not x.get('error') and x.get('classification_status') in ('ok','not_applicable')
                for x in card.get('figures',[]))
            and all(x.get('status')=='ok' and not x.get('error') for x in card.get('equations',[])))


def expected_coverage(paper):
    from read.api import evidence_preparation__equation_gaps as equation_gaps
    audit=paper.extraction_audit
    missing=sorted({r['number'] for r in audit.get('caption_candidates',[])}-{f.number for f in paper.figures})
    gaps=equation_gaps(paper)
    return {'figures':len(paper.figures),'equations':len([e for e in paper.equations if e.members]),
        'number_gaps':gaps,'figure_numbers_missing':missing,
        'truncated':bool(audit.get('context_omissions') or audit.get('figure_limit_exceeded') or audit.get('equation_limit_exceeded')),
        'unresolved':bool(gaps or missing or audit.get('sparse_text_pages')),'extraction_audit':audit}
