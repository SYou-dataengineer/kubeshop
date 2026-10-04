from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator


default_args = {
    "owner": "kubeshop-data-team",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


with DAG(
    dag_id="kubeshop_batch_analytics",
    description="Pipeline batch PySpark des ventes historiques KubeShop",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["kubeshop", "pyspark", "batch", "cassandra"],
) as dag:
    validate_sources = BashOperator(
        task_id="validate_source_files",
        bash_command=(
            "test -s /opt/airflow/data/orders.csv "
            "&& test -s /opt/airflow/data/products.json"
        ),
    )

    run_pyspark_batch = BashOperator(
        task_id="run_pyspark_batch",
        bash_command=(
            "spark-submit --master 'local[2]' "
            "/opt/airflow/jobs/batch_job.py "
            "--orders /opt/airflow/data/orders.csv "
            "--products /opt/airflow/data/products.json "
            "--output /opt/airflow/output "
            "--run-date '{{ ds }}'"
        ),
        execution_timeout=timedelta(minutes=15),
    )

    validate_batch_outputs = BashOperator(
        task_id="validate_batch_output_files",
        bash_command=(
            "test -s /opt/airflow/output/product_metrics.csv "
            "&& test -s /opt/airflow/output/daily_sales.csv "
            "&& test -s /opt/airflow/output/weekly_sales.csv "
            "&& test -s /opt/airflow/output/monthly_sales.csv"
        ),
    )

    build_bi_exports = BashOperator(
        task_id="build_powerbi_exports",
        bash_command=(
            "python /opt/airflow/jobs/bi_export.py "
            "--product-metrics /opt/airflow/output/product_metrics.csv "
            "--daily-sales /opt/airflow/output/daily_sales.csv "
            "--weekly-sales /opt/airflow/output/weekly_sales.csv "
            "--monthly-sales /opt/airflow/output/monthly_sales.csv "
            "--output /opt/airflow/output "
            "--run-date '{{ ds }}'"
        ),
        execution_timeout=timedelta(minutes=5),
    )

    validate_bi_outputs = BashOperator(
        task_id="validate_powerbi_output_files",
        bash_command=(
            "test -s /opt/airflow/output/dashboard_kpis.csv "
            "&& test -s /opt/airflow/output/product_analytics.csv "
            "&& test -s /opt/airflow/output/recommendations.csv "
            "&& test -s /opt/airflow/output/dashboard_summary.json"
        ),
    )

    (
        validate_sources
        >> run_pyspark_batch
        >> validate_batch_outputs
        >> build_bi_exports
        >> validate_bi_outputs
    )
