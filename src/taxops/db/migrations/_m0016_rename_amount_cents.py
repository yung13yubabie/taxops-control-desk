"""Migration 0016: rename amount_cents → amount in recurring billing tables.

The system stores NT$ integers (元), not 分. The _cents suffix was misleading.
"""

SQL = """
ALTER TABLE recurring_billing_lines
    RENAME COLUMN amount_cents TO amount;

ALTER TABLE recurring_billing_occurrences
    RENAME COLUMN confirmed_amount_cents TO confirmed_amount;
"""
