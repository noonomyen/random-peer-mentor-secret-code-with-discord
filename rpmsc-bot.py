from os import path, getenv
from sys import exit
from asyncio import Lock
from typing import Any, Optional
from random import shuffle
from datetime import datetime
from io import TextIOWrapper

import logging
import logging.handlers
import csv

from aiohttp import ClientSession
from dotenv import load_dotenv
from discord import Intents, Interaction, Member, TextStyle, ui, app_commands, Client as DiscordClient, Activity, ActivityType, Message, RawMessageDeleteEvent
from discord.ext import tasks

load_dotenv()

lock = Lock()
log_handler = logging.handlers.RotatingFileHandler(filename="rpmsc.log", encoding="utf-8")
log_handler.setFormatter(logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", style="{"))
logging.basicConfig(level=logging.DEBUG, handlers=[log_handler])
log = logging.getLogger("rpmsc")

class CodeGiven():
    log: logging.Logger
    data_f: TextIOWrapper
    data: dict[tuple[int, str], tuple[datetime, int, str, str]]
    record: list[tuple[str, int, str, int, str, str]]

    def __init__(self) -> None:
        self.log = logging.getLogger("rpmsc.code-given")
        self.data = {}
        self.record = []

        self.data_f = open("given.csv", "a+", newline="", encoding="utf-8")
        self.data_f.seek(0)
        for row in csv.reader(self.data_f):
            time, _, mentee_std_id, mentee_name, mentor_std_id, mentor_name, mentor_secret_code = row
            self.data[(int(mentee_std_id), mentee_name)] = (datetime.fromisoformat(time), int(mentor_std_id), mentor_name, mentor_secret_code)

        self.data_w = csv.writer(self.data_f, delimiter=",")

        self.log.info(f"Number of mentee code given : {len(self.data)}")

    def set(self, uid: int, time: datetime, mentee_std_id: int, mentee_name: str, mentor_data: tuple[int, str, str]) -> None:
        self.log.info(f"Set Mentor of {mentee_std_id}:'{mentee_name}' is {mentor_data[0]}:'{mentor_data[1]}'")
        self.data[(int(mentee_std_id), mentee_name)] = (time, mentor_data[0], mentor_data[1], mentor_data[2])
        self.record.append((time.isoformat(), mentee_std_id, mentee_name, mentor_data[0], mentor_data[1], mentor_data[2]))
        self.data_w.writerow((time.isoformat(), uid, mentee_std_id, mentee_name, mentor_data[0], mentor_data[1], mentor_data[2]))

    def get(self, mentee_std_id: int, mentee_name: str) -> Optional[tuple[datetime, int, str, str]]:
        try:
            return self.data[(mentee_std_id, mentee_name)]
        except KeyError as err:
            self.log.critical(err)
            return None

    def __contains__(self, mentee_data: tuple[int, str]) -> bool:
        return (mentee_data[0], mentee_data[1]) in self.data

class Resource():
    mentee_data: dict[int, str]
    mentor_data: list[tuple[int, str, str]]
    current: list[tuple[int, str, str]]
    state_f: TextIOWrapper
    log: logging.Logger

    def __init__(self) -> None:
        self.log = logging.getLogger("rpmsc.resource")
        self.mentee_data = {}
        self.mentor_data = []

        self.state_f = open("state.txt", "r+", encoding="utf-8")

        for std_id, name, secret_code in csv.reader(open("mentor.csv", "r")):
            self.mentor_data.append((int(std_id), name, secret_code))

        for std_id, name in csv.reader(open("mentee.csv", "r")):
            self.mentee_data[int(std_id)] = name

        self.log.info(f"Number of mentee : {len(self.mentee_data)}")
        self.log.info(f"Number of mentor : {len(self.mentor_data)}")
        self.current = self.mentor_data.copy()

        for line in [x.replace("\n", "").strip() for x in reversed(self.state_f.readlines()) if x.replace("\n", "").strip() != ""]:
            if line == "REFILL": break

            std_id = int(line)
            for i in range(len(self.current)):
                if self.current[i][0] == std_id:
                    self.current.pop(i)
                    self.log.info(f"Load state pop stduent Id {std_id}")
                    break
        else:
            self.log.info(f"Refill")
            self.state_f.write("REFILL\n")

        self.log.info(f"Number of available in list : {len(self.current)}")

    async def get(self) -> tuple[int, str, str]:
        async with lock:
            if len(self.current) == 0:
                self.log.info(f"Refill")
                self.state_f.write("REFILL\n")
                self.current = self.mentor_data.copy()
            shuffle(self.current)
            item = self.current.pop(0)
            self.state_f.write(str(item[0]) + "\n")

            return (item[0], item[1], item[2])

class Client(DiscordClient):
    log: logging.Logger
    log_on_message: logging.Logger
    log_on_raw_message_delete: logging.Logger
    guild_id: int
    code_given_channel_id: int
    sheet_api_url: str
    resource: Resource
    code_given: CodeGiven
    command_tree: app_commands.CommandTree

    def __init__(self, *, intents: Intents, guild_id: int, sheet_api_url: str, **options: Any) -> None:
        self.log = logging.getLogger("rpmcs.client")
        self.log_on_message = logging.getLogger("rpmcs.client.on_message")
        self.log_on_raw_message_delete = logging.getLogger("rpmcs.client.on_raw_message_delete")

        super().__init__(intents=intents, **options)

        self.guild_id = guild_id
        self.sheet_api_url = sheet_api_url
        self.resource = Resource()
        self.code_given = CodeGiven()
        self.command_tree = app_commands.CommandTree(self)

        self.__load_command_tree()

        @tasks.loop(seconds=30)
        async def update_sheet() -> None:
            async with lock:
                raw_data = self.code_given.record.copy()
                self.code_given.record.clear()

            if len(raw_data) > 0:
                self.log.info(f"update_sheet new {len(raw_data)} record")
                async with ClientSession() as session:
                    data = []
                    for rec in raw_data:
                        data.append({
                            "time": rec[0],
                            "mentee_std_id": rec[1],
                            "mentee_name": rec[2],
                            "mentor_std_id": rec[3],
                            "mentor_name": rec[4],
                            "message": rec[5]
                        })
                    res = await session.post(self.sheet_api_url, json=data)
                    json = await res.json()
                    self.log.info(f"update_sheet response {json.get('status')}")

        self.update_sheet = update_sheet

    def __load_command_tree(self) -> None:
        client = self

        class ask_modal(ui.Modal):
            def __init__(self) -> None:
                super().__init__(title="Identification", timeout=180)

                self.add_item(ui.TextInput(
                    label="Enter your stduent Id",
                    min_length=11,
                    max_length=11,
                    row=1,
                    required=True,
                    placeholder="67XXXXXXXXX",
                    style=TextStyle.short
                ))

                self.add_item(ui.TextInput(
                    label="First name in without prefix name",
                    row=2,
                    required=True,
                    placeholder="ชื่อ",
                    style=TextStyle.short
                ))

                self.add_item(ui.TextInput(
                    label="Last name in",
                    row=3,
                    required=True,
                    placeholder="นามสกุล",
                    style=TextStyle.short
                ))

            async def on_submit(self, interaction: Interaction) -> None:
                try:
                    std_id: int = int(self.children[0].value) # type: ignore
                except ValueError:
                    await interaction.response.send_message("Student ID is incorrect")
                    return

                first_name: str = self.children[1].value # type: ignore
                last_name: str = self.children[2].value # type: ignore
                full_name = first_name + " " + last_name

                if std_id in client.resource.mentee_data:
                    if client.resource.mentee_data[std_id] == full_name:
                        if (std_id, full_name) in client.code_given:
                            val = client.code_given.get(std_id, full_name)
                            if val:
                                time, _0, _1, mentor_secret_code = val
                                await interaction.response.send_message(f"**You have already chosen a random word**\n**Time: **{time}\n**Message: **`{mentor_secret_code}`", ephemeral=True)
                            else:
                                await interaction.response.send_message(f"You have already chosen a random word, but server is error, can't get data", ephemeral=True)
                        else:
                            mentor_id, mentor_name, mentor_secret_code = await client.resource.get()
                            client.code_given.set(interaction.user.id, interaction.created_at, std_id, full_name, (mentor_id, mentor_name, mentor_secret_code))
                            await interaction.response.send_message(f"**Your message is : **`{mentor_secret_code}`", ephemeral=True)
                    else:
                        await interaction.response.send_message(f"**Full name doesn't match**", ephemeral=True)
                else:
                    await interaction.response.send_message(f"**Not found this student ID**", ephemeral=True)

        @self.command_tree.command(name="give-code", description="Random secret or message code for peer mentee (freshy) to find peer mentor, good luck", guild=self.get_guild(self.guild_id))
        async def give_code(interaction: Interaction):
            if interaction.guild_id == self.guild_id and isinstance(interaction.user, Member):
                await interaction.response.send_modal(ask_modal())

    async def on_ready(self) -> None:
        self.log.info(f"Logged in as {self.user}")

        await self.change_presence(activity=Activity(
                type=ActivityType.listening,
                name="all freshy"
            )
        )

        await self.command_tree.sync()
        self.update_sheet.start()

    async def on_message(self, message: Message) -> None:
        if message.guild and message.guild.id == self.guild_id:
            self.log_on_message.info(str(message))

    async def on_raw_message_delete(self, payload: RawMessageDeleteEvent) -> None:
        if payload.guild_id == self.guild_id:
            self.log_on_raw_message_delete.info(str(payload))

if __name__ == "__main__":
    if not path.exists("mentor.csv"):
        print("not found mentor.csv file")
        exit(1)

    bot_token = getenv("DISCORD_RPMSC_TOKEN")
    guild_id = getenv("LISTEN_GUILD_ID")
    sheet_api_url = getenv("SHEET_API_URL")

    if bot_token is None or guild_id is None or sheet_api_url is None:
        print("DISCORD_RPMSC_TOKEN and LISTEN_GUILD_ID and and SHEET_API_URL is required in env")
        exit(1)

    client = Client(intents=Intents.all(), guild_id=int(guild_id), sheet_api_url=sheet_api_url, max_messages=None)
    client.run(token=bot_token, reconnect=True, log_handler=log_handler)
