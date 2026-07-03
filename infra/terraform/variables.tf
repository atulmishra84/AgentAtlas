variable "aws_region" {
  description = "AWS region for MVP deployment"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "mvp"
}

variable "project_name" {
  type    = string
  default = "agentatlas"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "azs" {
  description = "Two AZs is enough for MVP — not three"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "container_image_tag" {
  description = "Image tag pushed by CI — overridden per deploy"
  type        = string
  default     = "latest"
}

variable "ecs_task_cpu" {
  description = "Fargate task CPU units — 512 = 0.5 vCPU, fine for MVP load"
  type        = string
  default     = "512"
}

variable "ecs_task_memory" {
  type    = string
  default = "1024"
}

variable "ecs_desired_count" {
  description = "MVP runs 2 tasks for basic HA without overspending"
  type        = number
  default     = 2
}

variable "ecs_max_count" {
  type    = number
  default = 4
}

variable "db_instance_class" {
  description = "db.t4g.micro is enough for MVP/demo traffic — burstable, cheap"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "domain_name" {
  description = "Optional — leave blank to use the ALB DNS name directly for demo"
  type        = string
  default     = ""
}

variable "alert_email" {
  type    = string
  default = "platform-team@veliqhq.com"
}
