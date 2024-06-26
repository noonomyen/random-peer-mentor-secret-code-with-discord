from os import path, getenv
from sys import exit
from asyncio import Lock
from typing import Any, Callable, Optional, Coroutine
from random import randint
from datetime import datetime

import logging
import logging.handlers
import csv

from aiohttp import ClientSession
from requests import Session
from dotenv import load_dotenv
from discord import Intents, Interaction, Member, TextStyle, ui, app_commands, Client as DiscordClient, Activity, ActivityType
from discord.ext import tasks

load_dotenv(override=True)

lock = Lock()
log_handler = logging.handlers.RotatingFileHandler(filename="rpmsc.log", encoding="utf-8")
log_handler.setFormatter(logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", style="{"))
logging.basicConfig(level=logging.DEBUG, handlers=[log_handler])
log = logging.getLogger("rpmsc")

class CodeGiven():
    log: logging.Logger
    data: dict[tuple[int, str], tuple[datetime, int, str, str]]
    record: list[tuple[str, int, str, int, str, str]]

    def __init__(self) -> None:
        self.log = logging.getLogger("rpmsc.code-given")
        self.data = {}
        self.record = []

        for row in csv.reader(open("given.csv", "r", newline="", encoding="utf-8")):
            time, _, mentee_std_id, mentee_name, mentor_std_id, mentor_name, mentor_secret_code = row
            self.data[(int(mentee_std_id), mentee_name)] = (datetime.fromisoformat(time), int(mentor_std_id), mentor_name, mentor_secret_code)

        self.log.info(f"Number of mentee code given : {len(self.data)}")

    def set(self, uid: int, time: datetime, mentee_std_id: int, mentee_name: str, mentor_data: tuple[int, str, str]) -> None:
        self.log.info(f"Set Mentor of {mentee_std_id}:'{mentee_name}' is {mentor_data[0]}:'{mentor_data[1]}'")
        with open("given.csv", "a", newline="", encoding="utf-8") as f:
            csv.writer(f, delimiter=",").writerow((time.isoformat(), uid, mentee_std_id, mentee_name, mentor_data[0], mentor_data[1], mentor_data[2]))
        self.data[(int(mentee_std_id), mentee_name)] = (time, mentor_data[0], mentor_data[1], mentor_data[2])
        self.record.append((time.isoformat(), mentee_std_id, mentee_name, mentor_data[0], mentor_data[1], mentor_data[2]))

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
    log: logging.Logger

    def __init__(self) -> None:
        self.log = logging.getLogger("rpmsc.resource")
        self.mentee_data = {}
        self.mentor_data = []

        for std_id, name, secret_code in csv.reader(open("mentor.csv", "r")):
            self.mentor_data.append((int(std_id), name, secret_code))

        for std_id, name in csv.reader(open("mentee.csv", "r")):
            self.mentee_data[int(std_id)] = name

        self.log.info(f"Number of mentee : {len(self.mentee_data)}")
        self.log.info(f"Number of mentor : {len(self.mentor_data)}")
        self.current = self.mentor_data.copy()

        for line in [x.replace("\n", "").strip() for x in reversed(open("state.txt", "r", encoding="utf-8").readlines()) if x.replace("\n", "").strip() != ""]:
            if line == "REFILL": break

            std_id = int(line)
            for i in range(len(self.current)):
                if self.current[i][0] == std_id:
                    self.current.pop(i)
                    self.log.info(f"Load state pop stduent Id {std_id}")
                    break
        else:
            self.log.info(f"Refill")
            with open("state.txt", "a", encoding="utf-8") as f:
                f.write("REFILL\n")

        self.log.info(f"Number of available in list : {len(self.current)}")

    async def get(self) -> tuple[int, str, str]:
        async with lock:
            if len(self.current) == 0:
                self.log.info(f"Refill")
                with open("state.txt", "a", encoding="utf-8") as f:
                    f.write("REFILL\n")
                self.current = self.mentor_data.copy()
            item = self.current.pop(randint(0, len(self.current) - 1))
            with open("state.txt", "a", encoding="utf-8") as f:
                f.write(str(item[0]) + "\n")

            return (item[0], item[1], item[2])

class Client(DiscordClient):
    guild_id: int
    code_given_channel_id: int
    sheet_api_url: str
    start_time: datetime
    end_time: datetime
    require_sync_app_command: bool
    tmp_given_record: list[tuple[str, int, str, int, str, str]]

    log: logging.Logger
    resource: Resource
    code_given: CodeGiven
    command_tree: app_commands.CommandTree
    task_update_sheet: tasks.Loop[Callable[[], Coroutine[Any, Any, None]]]

    def __init__(self, *, intents: Intents, guild_id: int, sheet_api_url: str, start_end_time: tuple[datetime, datetime], require_sync_app_command = False, **options: Any) -> None:
        self.log = logging.getLogger("rpmcs.client")

        super().__init__(intents=intents, **options)

        self.guild_id = guild_id
        self.sheet_api_url = sheet_api_url
        self.start_time, self.end_time = start_end_time
        self.tmp_given_record = []
        self.require_sync_app_command = require_sync_app_command
        self.resource = Resource()
        self.code_given = CodeGiven()
        self.command_tree = app_commands.CommandTree(self)

        self.__load_command_tree()

        @tasks.loop(seconds=30, count=None)
        async def task_update_sheet() -> None:
            async with lock:
                self.tmp_given_record += self.code_given.record.copy()
                self.code_given.record.clear()

            if len(self.tmp_given_record) > 0:
                self.log.info(f"task_update_sheet new {len(self.tmp_given_record)} record")
                async with ClientSession() as session:
                    data = []
                    for rec in self.tmp_given_record:
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
                    if json["status"] == "ok":
                        self.tmp_given_record.clear()
                        self.log.info(f"task_update_sheet Response {json['status']}")
                    else:
                        self.log.critical(f"task_update_sheet Response {json['status']}")
                        self.log.critical(f"task_update_sheet Failed to update data to sheet, number of record : {len(self.tmp_given_record)}")

        self.task_update_sheet = task_update_sheet

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
                    style=TextStyle.short
                ))

                self.add_item(ui.TextInput(
                    label="First + middle name without prefix name",
                    min_length=1,
                    row=2,
                    required=True,
                    style=TextStyle.short
                ))

                self.add_item(ui.TextInput(
                    label="Last name",
                    min_length=1,
                    row=3,
                    required=True,
                    style=TextStyle.short
                ))

            async def on_submit(self, interaction: Interaction) -> None:
                std_id_str = self.children[0].value # type: ignore
                first_name: str = self.children[1].value # type: ignore
                last_name: str = self.children[2].value # type: ignore

                client.log.info(f"ask_modal:on_submit [{repr(std_id_str)}, {repr(first_name)}, {repr(last_name)}] interaction_id:{interaction.id} user_id:{interaction.user.id} guild_channel_id:{interaction.guild_id}:{interaction.channel_id}")

                try:
                    std_id: int = int(std_id_str) # type: ignore
                except ValueError:
                    await interaction.response.send_message("Student ID is incorrect", ephemeral=True)
                    return

                first_name = first_name.strip()
                last_name = last_name.strip()

                if len(first_name) == 0 or len(last_name) == 0:
                    await interaction.response.send_message("First or last name must not be blank", ephemeral=True)
                    return

                full_name = first_name + " " + last_name

                if std_id in client.resource.mentee_data:
                    if client.resource.mentee_data[std_id] == full_name:
                        if (std_id, full_name) in client.code_given:
                            val = client.code_given.get(std_id, full_name)
                            if val:
                                time, _0, _1, mentor_secret_code = val
                                await interaction.response.send_message(f"You have already chosen a random word\nTime: {time}\n```txt\n{mentor_secret_code}\n```", ephemeral=True)
                            else:
                                await interaction.response.send_message(f"You have already chosen a random word, but server can't find data", ephemeral=True)
                        else:
                            mentor_id, mentor_name, mentor_secret_code = await client.resource.get()
                            client.code_given.set(interaction.user.id, interaction.created_at, std_id, full_name, (mentor_id, mentor_name, mentor_secret_code))
                            await interaction.response.send_message(f"Your message is\n```txt\n{mentor_secret_code}\n```", ephemeral=True)
                    else:
                        await interaction.response.send_message(f"Full name doesn't match", ephemeral=True)
                else:
                    await interaction.response.send_message(f"Not found this student ID", ephemeral=True)

        @self.command_tree.command(name="give-code", description="Random secret or message code for peer mentee (freshy) to find peer mentor, good luck", guild=self.get_guild(self.guild_id))
        async def give_code(interaction: Interaction):
            if interaction.guild_id == self.guild_id and isinstance(interaction.user, Member):
                self.log.info(f"app_command:give-code interaction_id:{interaction.id} user_id:{interaction.user.id} guild_channel_id:{interaction.guild_id}:{interaction.channel_id}")
                if interaction.created_at < client.start_time:
                    await interaction.response.send_message(f"The event will start <t:{int(client.start_time.timestamp())}:R>", ephemeral=True)
                elif interaction.created_at > client.end_time:
                    await interaction.response.send_message(f"Activity ended <t:{int(client.end_time.timestamp())}:R>", ephemeral=True)
                else:
                    await interaction.response.send_modal(ask_modal())
            else:
                await interaction.response.send_message("This command is not allowed from outside", ephemeral=True)

    async def on_ready(self) -> None:
        self.log.info(f"Logged in as {self.user}")

        await self.change_presence(activity=Activity(
                type=ActivityType.listening,
                name="all freshy"
            )
        )

        if self.require_sync_app_command:
            await self.command_tree.sync()
            self.log.info("App command is synced")
            open("app-command-synced", "w").write("")
        else:
            self.log.info("Skip app command sync")

        if not self.task_update_sheet.is_running():
            self.task_update_sheet.start()
            self.log.info(f"Start task loop task_update_sheet")

if __name__ == "__main__":
    if not path.exists("mentor.csv"):
        log.critical("Not found mentor.csv file")
        exit(1)

    if not path.exists("mentee.csv"):
        log.critical("Not found mentee.csv file")
        exit(1)

    bot_token = getenv("DISCORD_RPMSC_TOKEN")
    guild_id = getenv("LISTEN_GUILD_ID")
    sheet_api_url = getenv("SHEET_API_URL")
    start_time = getenv("START")
    end_time = getenv("END")

    require_sync_app_command = not path.exists("app-command-synced")

    if bot_token is None or guild_id is None or sheet_api_url is None or start_time is None or end_time is None:
        log.critical("DISCORD_RPMSC_TOKEN, LISTEN_GUILD_ID, SHEET_API_URL, START, END is required in env")
        exit(1)

    try:
        with Session() as session:
            res = session.get(sheet_api_url, timeout=30)
            if res.status_code == 200:
                try:
                    data = res.json()
                    if data["status"] != "ok":
                        raise Exception(f"Sheet API Error, Server return status = {data['status']}")
                except Exception as err:
                    log.critical(err)
                    exit(1)
            else:
                log.critical(f"Sheet API Error, Server return status code is {res.status_code}")
                exit(1)
    except SystemExit as err:
        exit(err.code)
    except Exception as err:
        log.critical("Sheet API, " + str(err))
        exit(1)

    log.info("Sheet API is OK")

    client = Client(
        intents=Intents.none(),
        guild_id=int(guild_id),
        sheet_api_url=sheet_api_url,
        start_end_time=(
            datetime.fromisoformat(start_time),
            datetime.fromisoformat(end_time)
        ),
        max_messages=None,
        require_sync_app_command=require_sync_app_command
    )

    client.run(token=bot_token, reconnect=True, log_handler=log_handler)
