"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
    )
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("published", sa.JSON(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("streams")
    op.drop_table("campaigns")
