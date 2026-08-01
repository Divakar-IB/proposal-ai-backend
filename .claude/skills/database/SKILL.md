---
name: database
description: Use when creating or modifying database models, SQLAlchemy models, Alembic migrations, relationships, enums, indexes, constraints, or repository queries.
---

# Database Skill

## Purpose

This skill governs all database design, SQLAlchemy models, relationships, enums, and Alembic migrations for the Proposal AI backend.

Tech Stack

- PostgreSQL
- SQLAlchemy 2.x Async ORM
- Alembic
- AsyncPG

---

# Database Design Principles

Design the database for maintainability and scalability.

Always:

- Normalize data unless there is a strong reason not to.
- Create only the columns required by the current feature.
- Avoid speculative columns ("might be needed later").
- Keep tables focused on a single responsibility.
- Use meaningful table and column names.
- Prefer explicit relationships over duplicated data.

Never:

- Add unused columns.
- Store derived values unless performance requires it.
- Duplicate information across tables.
- Introduce nullable columns without justification.

---

# Creating New Models

Whenever a new feature requires persistence:

1. Analyze the feature.
2. Identify only the required entities.
3. Design relationships.
4. Create SQLAlchemy models.
5. Create Alembic migration.
6. Verify migration.
7. Update repositories if necessary.

Never stop after creating only the model.

A database change is incomplete until the migration exists.

---

# Model Standards

Every model should include:

- Primary key
- created_at
- updated_at

Include deleted_at only if soft delete is required.

Use SQLAlchemy 2.x style.

Example:

- Mapped[]
- mapped_column()
- relationship()

Avoid legacy SQLAlchemy syntax.

---

# Column Design

Choose the smallest appropriate datatype.

Examples

UUID
Integer
BigInteger
String(length)
Text
Boolean
DateTime(timezone=True)
JSONB
ARRAY
Enum

Do not use Text when String(length) is sufficient.

Do not use String without considering an appropriate length unless the value is genuinely unbounded.

---

# Naming Conventions

Tables

snake_case plural

Examples

users

knowledge_documents

proposal_generations

proposal_sections

Columns

snake_case

Foreign Keys

user_id

proposal_id

knowledge_document_id

Boolean columns

is_active

is_deleted

is_completed

Timestamps

created_at

updated_at

deleted_at

---

# Relationships

Always create proper ORM relationships.

If using ForeignKey:

Also create relationship() on both sides.

Example

Proposal

↓

ProposalSection

Both models should contain relationships.

Specify

back_populates

cascade

lazy loading strategy when appropriate

Never create orphan foreign keys.

---

# Foreign Keys

Every foreign key must:

- reference the correct table
- use ForeignKey()
- have an ORM relationship
- be indexed when frequently queried

Think carefully before enabling cascade delete.

Prefer explicit delete behavior.

---

# Constraints

Always consider

NOT NULL

UNIQUE

CHECK

Foreign Keys

Composite Unique Constraints

Examples

A user cannot have two documents with the same filename in the same folder.

A proposal section order should be unique within a proposal.

---

# Indexes

Create indexes for

Foreign Keys

Frequently filtered columns

Search columns

Status columns

Never create unnecessary indexes.

Remember every index has write overhead.

---

# Enums

Prefer Python Enum classes.

Map using SQLAlchemy Enum.

Do not hardcode string literals throughout the codebase.

When modifying enums:

- update Enum
- generate migration
- verify PostgreSQL enum migration

---

# JSON Fields

Use JSONB only for semi-structured data.

Never use JSONB for relational data.

If data is relational,

create another table.

---

# Soft Delete

Use soft delete only when business requirements need recovery.

Otherwise use hard delete.

Do not automatically add

is_deleted

deleted_at

to every model.

---

# Audit Columns

Include

created_at

updated_at

Use server defaults whenever appropriate.

---

# Migration Rules

Whenever any of the following changes:

- new table
- new column
- removed column
- renamed column
- enum changes
- constraint changes
- indexes
- relationships

Immediately create an Alembic migration.

Never leave models and database schema out of sync.

Migration naming examples

create_proposals_table

add_status_to_proposals

add_document_type_enum

create_knowledge_indexes

rename_requirement_column

Migration should be reviewed before applying.

---

# Migration Verification

Before considering the task complete:

✓ Model created

✓ Relationships verified

✓ Alembic migration generated

✓ Migration reviewed

✓ Migration applied

✓ No migration conflicts

---

# Performance

Avoid

N+1 queries

Unnecessary joins

Loading entire tables

Prefer

selectinload()

joinedload()

proper pagination

indexed filters

---

# Repository Layer

Database access belongs only inside repositories.

Models should not contain business logic.

Routers must never execute SQL.

Services coordinate repositories.

---

# Data Integrity

Always protect integrity.

Use

Foreign Keys

Unique Constraints

Transactions

Database constraints

Do not rely only on application validation.

---

# Before Completing Any Database Task

Verify

✓ Correct table names

✓ Correct column names

✓ Minimal required columns only

✓ Correct datatypes

✓ Proper nullable settings

✓ Relationships created

✓ Foreign keys mapped

✓ Constraints added

✓ Indexes evaluated

✓ Enum correctness

✓ Alembic migration created

✓ Migration tested

✓ Repository updated if needed

If any item is missing, the database task is not complete.