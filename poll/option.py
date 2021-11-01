from typing import Generator, Iterable, List, Optional, Set, Tuple, TYPE_CHECKING
import asyncpg
import sql

if TYPE_CHECKING:
	from poll.poll import Poll


class Option:
	"""Represents an option that a user can choose in a poll."""

	def __init__(
		self,
		option_id: int,
		label: str,
		votes: Iterable[int],
		pool: asyncpg.Pool,
		author_id: Optional[int],
	):
		"""NOTE: Always set self.poll after constructing this object."""
		self.__option_id = option_id
		self.__label = label
		self.__votes = set(votes)
		self.__poll: Poll
		self.__pool = pool
		self.__author_id = author_id

	@property
	def option_id(self) -> int:
		"""The id of the option."""
		return self.__option_id

	@property
	def label(self) -> str:
		"""The label of the option."""
		return self.__label

	@property
	def votes(self) -> Set[int]:
		"""The set of IDs of members who voted on this option."""
		return self.__votes.copy()

	@property
	def poll(self) -> "Poll":
		"""The Poll that the option belongs to."""
		return self.__poll

	@poll.setter
	def poll(self, poll: "Poll"):
		"""Remember to always set this property after construction. It is not done in construction because polls can't be created before their options."""
		self.__poll = poll

	@property
	def pool(self) -> asyncpg.Connection:
		"""Get the connection pool to the database which holds this option."""
		return self.__pool

	@property
	def author_id(self) -> Optional[int]:
		"""The ID of the member who added the option, or None if the option existed from poll creation."""
		return self.__author_id

	@property
	def vote_count(self) -> int:
		"""Get the number of votes for this option."""
		return len(self.__votes)

	async def remove_vote(self, voter_id: int):
		"""Remove a vote from the given user on this option. If no such vote exists, nothing happens.

		Args:
			voter_id (int): The ID of the user whose vote is to be removed.
		"""
		await sql.delete(
			self.pool, "votes", option_id=self.option_id, voter_id=voter_id
		)
		self.__votes.discard(voter_id)

	async def add_vote(self, voter_id: int):
		"""Add a vote from the given user on this option. If such a vote already exists, nothing happens. If the poll cannot have more than one vote per user, all other votes from this user are removed.

		Args:
			voter_id (int): The ID of the user whose vote is to be added.
		"""
		if not self.poll.allow_multiple_votes:
			await self.poll.remove_votes_from(voter_id)
		await sql.insert.one(
			self.pool,
			"votes",
			on_conflict="DO NOTHING",
			option_id=self.option_id,
			voter_id=voter_id,
		)
		self.__votes.add(voter_id)

	async def toggle_vote(self, voter_id: int):
		"""Toggle a user's vote on this option. If adding their vote would cause too many votes from the same user, the rest of their votes are removed.

		Args:
			voter_id (int): The ID of the user to toggle the vote of.
		"""
		if voter_id in self.votes:
			await self.remove_vote(voter_id)
		else:
			await self.add_vote(voter_id)

	@classmethod
	async def get_voters(cls, pool: asyncpg.Pool, option_id: int) -> Set[int]:
		"""Fetch the IDs of all the voters for a given option from the database.

		Args:
			pool (asyncpg.Pool): The connection pool to the database.
			option_id (int): The ID of the option to fetch the voters for.

		Returns:
			List[int]: A list of the IDs of the members who voted on the option.
		"""
		return {
			r["voter_id"]
			for r in await sql.select.many(
				pool, "votes", ("voter_id",), option_id=option_id
			)
		}

	@classmethod
	async def create_options(
		cls,
		labels: Iterable[str],
		poll_id: int,
		pool: asyncpg.Pool,
		author_id: Optional[int] = None,
	) -> Generator["Option", None, None]:
		"""Create new Option objects for the given poll and add them to the database.

		NOTE: Don't forget to set option.poll on each returned option after calling this function.

		Args:
			labels (str): The labels of the options to add.
			poll_id (int): The ID of the poll that this option belongs to.
			pool (asyncpg.Pool): The connection pool to use to insert the options.
			author_id (Optional[int], optional): The ID of the person who added this option, or None if the options were created at the time of creation.

		Returns:
			Generator[Option, ...]: The new Option objects.
		"""
		records = await sql.insert.many(
			pool,
			"options",
			("label", "poll_id", "author"),
			[(label, poll_id, author_id) for label in labels],
			returning="id, label",
		)
		return (cls(r["id"], r["label"], (), pool, author_id) for r in records)

	@classmethod
	async def get_options_of_poll(
		cls, pool: asyncpg.Pool, poll_id: int
	) -> List["Option"]:
		"""Get the options of a poll given its ID.

		NOTE: Don't forget to set option.poll for each returned option after calling this function.

		Args:
			pool (asyncpg.Pool): The connection pool to use to fetch the options.
			poll_id (int): The ID of the poll to get the options of.

		Returns:
			List[Option]: A list of Option objects belonging to the given poll.
		"""
		records = await sql.select.many(
			pool, "options", ("id", "label", "author"), poll_id=poll_id
		)
		return [
			cls(
				r["id"],
				r["label"],
				await cls.get_voters(pool, r["id"]),
				pool,
				r["author"],
			)
			for r in records
		]
