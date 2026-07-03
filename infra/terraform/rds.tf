# ── RDS PostgreSQL — single-AZ for MVP ──────────────────────────────────────
# MVP decision: single-AZ (not Multi-AZ) saves ~50% on RDS cost.
# Current backend uses in-memory storage, so this provisions the path to
# persistent storage for the next milestone (replacing AGENTS_DB dict with
# real Postgres) without blocking the MVP demo on it.

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${var.project_name}-db-subnet" }
}

resource "random_password" "db_password" {
  length  = 24
  special = false # avoid URL-encoding issues in connection strings
}

resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "${var.project_name}/${var.environment}/db-credentials"
  recovery_window_in_days = 0 # MVP: allow immediate deletion, no 30-day hold
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = "agentatlas_app"
    password = random_password.db_password.result
    engine   = "postgres"
    host     = aws_db_instance.main.address
    port     = 5432
    dbname   = "agentatlas"
  })
}

resource "aws_db_instance" "main" {
  identifier     = "${var.project_name}-${var.environment}"
  engine         = "postgres"
  engine_version = "16.4"

  instance_class        = var.db_instance_class
  allocated_storage      = var.db_allocated_storage
  storage_type            = "gp3"
  storage_encrypted       = true

  db_name  = "agentatlas"
  username = "agentatlas_app"
  password = random_password.db_password.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  multi_az            = false  # MVP — flip to true when this goes to prod
  backup_retention_period = 3  # short window, MVP only needs rollback for testing
  skip_final_snapshot     = true   # MVP: fast teardown; remove for prod
  deletion_protection     = false  # MVP: allow `terraform destroy`; enable for prod

  performance_insights_enabled = false  # cost saver — turn on for prod tuning

  tags = { Name = "${var.project_name}-postgres" }
}
