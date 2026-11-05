"""A member of a new household whose default model is the served one, signed in."""

from __future__ import annotations

from dataclasses import dataclass

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.server import Server


@dataclass(frozen=True)
class Member:
    account: Account
    token: str
    model: HouseholdModel


def new_member(database: Database, server: Server, harness_model: HarnessModel) -> Member:
    account = create_account(database, create_tenant(database))
    model = harness_model.connect(account.tenant_id)
    return Member(account, login(server, account), model)
