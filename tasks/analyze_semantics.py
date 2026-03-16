from pathlib import Path

from analyzers.domain_semantic_analyzer import DomainSemanticAnalyzer
from tools.report_tools import write_json_report


def run_semantic_analysis(
    db_models_analysis_json: Path,
    project_rules_json: Path,
):

    analyzer = DomainSemanticAnalyzer(
        db_models_analysis_json=db_models_analysis_json,
        project_rules_json=project_rules_json,
    )

    result = analyzer.analyze()

    output_path = Path("reports/field_semantics.json")

    write_json_report(output_path, result)

    return result, output_path
