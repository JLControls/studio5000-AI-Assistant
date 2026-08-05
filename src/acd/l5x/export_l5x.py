import argparse
import os
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Cursor
from typing import Dict, List, Union

from acd.database.dbextract import DbExtract
from acd.zip.unzip import Unzip
from loguru import logger as log

from acd.l5x.elements import (
    Controller,
    ControllerBuilder,
    ProjectBuilder,
    RSLogix5000Content,
)
from acd.record.comments import CommentsRecord
from acd.record.comps import CompsRecord
from acd.record.nameless import NamelessRecord
from acd.record.sbregion import SbRegionRecord


def _parse_regn_links(
    data: bytes,
    routine_ids: set[int],
    rung_ids: set[int],
) -> List[tuple[int, int, int, int]]:
    """Recover Studio v38 routine/rung links from ``RegnLink.Dat``.

    Each link is a 22-byte record containing a 16-bit comment key, a routine
    object ID, the current rung object ID, and the next rung object ID. The
    database has a non-record header and padding, so candidates are validated
    against object IDs already parsed from Comps.Dat and SbRegion.Dat.
    """
    links: List[tuple[int, int, int, int]] = []
    offset = 0
    active_tail = b"\x00\x00\x02\x00\x00\x01"
    final_tail = b"\x00" * 6
    erased_final_tail = b"\xff" * 6
    while offset + 22 <= len(data):
        comment_key, _ordinal, routine_id, rung_id, next_rung_id = struct.unpack_from(
            "<HHIII", data, offset
        )
        tail = data[offset + 16 : offset + 22]
        valid_next = next_rung_id == 0xFFFFFFFF or next_rung_id in rung_ids
        if (
            routine_id in routine_ids
            and rung_id in rung_ids
            and valid_next
            and tail in (active_tail, final_tail, erased_final_tail)
        ):
            links.append((comment_key, routine_id, rung_id, next_rung_id))
            offset += 22
        else:
            offset += 1
    return links


def _restore_rung_order_from_links(
    cur: Cursor,
    links: List[tuple[int, int, int, int]],
) -> None:
    """Supplement truncated Region Map data with the RegnLink rung chain."""
    links_by_routine: Dict[int, Dict[int, int]] = {}
    for _key, routine_id, rung_id, next_rung_id in links:
        links_by_routine.setdefault(routine_id, {})[rung_id] = next_rung_id

    for routine_id, next_by_rung in links_by_routine.items():
        cur.execute(
            "SELECT object_id, unknown FROM region_map WHERE parent_id=? ORDER BY unknown",
            (routine_id,),
        )
        existing_rows = cur.fetchall()
        if not existing_rows:
            continue

        start_rung = existing_rows[0][0]
        ordered_rungs: List[int] = []
        seen: set[int] = set()
        rung_id = start_rung
        while rung_id != 0xFFFFFFFF and rung_id not in seen:
            seen.add(rung_id)
            ordered_rungs.append(rung_id)
            rung_id = next_by_rung.get(rung_id, 0xFFFFFFFF)

        if len(ordered_rungs) <= len(existing_rows):
            continue

        existing_ids = {row[0] for row in existing_rows}
        for position, ordered_id in enumerate(ordered_rungs):
            if ordered_id in existing_ids:
                cur.execute(
                    "UPDATE region_map SET unknown=? WHERE parent_id=? AND object_id=?",
                    (position, routine_id, ordered_id),
                )
            else:
                cur.execute(
                    "INSERT INTO region_map VALUES (?, ?, ?, ?, ?)",
                    (
                        ordered_id,
                        routine_id,
                        position,
                        0xFFFFFFFF,
                        struct.pack("<IIII", routine_id, position, 0xFFFFFFFF, ordered_id),
                    ),
                )


@dataclass
class ExportL5x:
    input_filename: os.PathLike
    _temp_dir: str = "build"  # tempfile.mkdtemp()
    _controller: Union[Controller, None] = None
    _project: Union[RSLogix5000Content, None] = None

    def __post_init__(self):
        log.info(
            "Creating temporary directory (if it doesn't exist to store ACD database files - "
            + self._temp_dir
        )
        _DEFAULT_SQL_DATABASE_NAME = "acd.db"
        if os.path.exists(os.path.join(self._temp_dir, _DEFAULT_SQL_DATABASE_NAME)):
            os.remove(os.path.join(self._temp_dir, _DEFAULT_SQL_DATABASE_NAME))
        if not os.path.exists(os.path.join(self._temp_dir)):
            os.makedirs(self._temp_dir)
        log.info("Creating sqllite database to store ACD database records")
        self._db = sqlite3.connect(
            os.path.join(self._temp_dir, _DEFAULT_SQL_DATABASE_NAME)
        )
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=OFF")
        self._cur: Cursor = self._db.cursor()

        log.debug("Create Comps table in sqllite db")
        self._cur.execute(
            "CREATE TABLE comps(object_id int, parent_id int, comp_name text, seq_number int, record_type int, record BLOB NOT NULL)"
        )
        log.debug("Create pointers table in sqllite db")
        self._cur.execute(
            "CREATE TABLE pointers(object_id int, parent_id int, comp_name text, seq_number int, record_type int, record BLOB NOT NULL)"
        )
        log.debug("Create Rungs table in sqllite db")
        self._cur.execute(
            "CREATE TABLE rungs(object_id int, rung text, seq_number int)"
        )
        log.debug("Create Region_map table in sqllite db")
        self._cur.execute(
            "CREATE TABLE region_map(object_id int, parent_id int, unknown int, seq_no int, record BLOB NOT NULL)"
        )
        log.debug("Create Comments table in sqllite db")
        self._cur.execute(
            "CREATE TABLE comments(seq_number int, sub_record_length int, object_id int, record_string text, record_type int, parent int, tag_reference text, rung_content int, member_ref int)"
        )

        log.debug("Create Nameless table in sqllite db")
        self._cur.execute(
            "CREATE TABLE nameless(object_id int, parent_id int, record BLOB NOT NULL)"
        )
        self._cur.execute(
            "CREATE TABLE regn_links(comment_key int, routine_id int, rung_id int, next_rung_id int)"
        )

        log.info("Extracting ACD database file")
        unzip = Unzip(self.input_filename)
        unzip.write_files(self._temp_dir)

        # Preserve all embedded files in original order for round-trip writing.
        # Read directly from the ACD archive (pre-decompression) so that
        # compressed files are carried as-is and write-back is byte-identical.
        self._file_order: List[str] = [r.filename for r in unzip.records]
        self._footer_unknown: int = unzip.header._unknown_two
        self._raw_files: Dict[str, bytes] = {}
        with open(self.input_filename, "rb") as acd_fh:
            for record in unzip.records:
                acd_fh.seek(record.file_offset)
                self._raw_files[record.filename] = acd_fh.read(record.file_length)

        log.info("Getting records from ACD Comps file and storing in sqllite database")
        comps_db = DbExtract(os.path.join(self._temp_dir, "Comps.Dat")).read()
        # Deduplicate by object_id. When duplicate object_ids exist (e.g. a routine that
        # appears twice in Comps.Dat with different record_type values), keep the entry
        # with the largest record because the smaller/later entry is typically a truncated
        # or partial record (e.g. record_type=271 vs 259 for routines) that fails to parse
        # correctly with RxGeneric. The full record is always the largest one.
        comps_by_id = {}
        for record in comps_db.records.record:
            t = CompsRecord.parse(record)
            if t is not None:
                oid = t[0]
                if oid not in comps_by_id or len(t[5]) > len(comps_by_id[oid][5]):
                    comps_by_id[oid] = t
        self._cur.executemany("INSERT INTO comps VALUES (?,?,?,?,?,?)", comps_by_id.values())
        self._db.commit()

        # Build name lookup for SbRegion tag reference resolution (object_id → comp_name).
        # Store on self for use during write-back (patch_sbregion_dat needs id_to_name).
        name_lookup = {oid: t[2] for oid, t in comps_by_id.items()}
        self._id_to_name: Dict[int, str] = name_lookup

        log.info(
            "Getting records from ACD Region Map file and storing in sqllite database"
        )
        self.populate_region_map()

        log.info(
            "Getting records from ACD SbRegion file and storing in sqllite database"
        )
        sb_region_db = DbExtract(os.path.join(self._temp_dir, "SbRegion.Dat")).read()
        rung_tuples = [t for record in sb_region_db.records.record if (t := SbRegionRecord.parse(record, name_lookup)) is not None]
        self._cur.executemany("INSERT INTO rungs VALUES (?,?,?)", rung_tuples)
        self._db.commit()

        # Studio v38 stores the complete rung chain and comment-to-rung keys in
        # RegnLink.Dat. This also repairs a known truncated Region Map entry.
        regn_link_path = os.path.join(self._temp_dir, "RegnLink.Dat")
        if os.path.exists(regn_link_path):
            self._cur.execute("SELECT DISTINCT parent_id FROM region_map")
            routine_ids = {row[0] for row in self._cur.fetchall()}
            self._cur.execute("SELECT object_id FROM rungs")
            rung_ids = {row[0] for row in self._cur.fetchall()}
            with open(regn_link_path, "rb") as regn_link_file:
                regn_links = _parse_regn_links(
                    regn_link_file.read(), routine_ids, rung_ids
                )
            self._cur.executemany(
                "INSERT INTO regn_links VALUES (?,?,?,?)", regn_links
            )
            _restore_rung_order_from_links(self._cur, regn_links)
            self._db.commit()

        log.info(
            "Getting records from ACD Comments file and storing in sqllite database"
        )
        comments_db = DbExtract(os.path.join(self._temp_dir, "Comments.Dat")).read()
        comment_tuples = [t for record in comments_db.records.record if (t := CommentsRecord.parse(record)) is not None]
        self._cur.executemany("INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?)", comment_tuples)
        self._db.commit()

        log.info(
            "Getting records from ACD Nameless file and storing in sqllite database"
        )
        nameless_db = DbExtract(os.path.join(self._temp_dir, "Nameless.Dat")).read()
        nameless_tuples = [t for record in nameless_db.records.record if (t := NamelessRecord.parse(record)) is not None]
        self._cur.executemany("INSERT INTO nameless VALUES (?,?,?)", nameless_tuples)
        self._db.commit()

        log.info("Creating indexes for fast object graph queries")
        self._cur.execute("CREATE INDEX idx_comps_object_id ON comps(object_id)")
        self._cur.execute("CREATE INDEX idx_comps_parent_id ON comps(parent_id)")
        self._cur.execute("CREATE INDEX idx_comps_parent_name ON comps(parent_id, comp_name)")
        self._cur.execute("CREATE INDEX idx_rungs_object_id ON rungs(object_id)")
        self._cur.execute("CREATE INDEX idx_region_map_parent_id ON region_map(parent_id)")
        self._cur.execute("CREATE INDEX idx_comments_parent ON comments(parent)")
        self._cur.execute(
            "CREATE INDEX idx_regn_links_routine_key ON regn_links(routine_id, comment_key)"
        )
        self._db.commit()

    @property
    def controller(self):
        if self._controller is None:
            self._controller = ControllerBuilder(self._cur).build()
        return self._controller

    @property
    def project(self):
        if self._project is None:
            self._project = ProjectBuilder(
                Path(os.path.join(self._temp_dir, "QuickInfo.XML"))
            ).build()
            self._project.controller = self.controller
            self._project._raw_files = self._raw_files
            self._project._file_order = self._file_order
            self._project._footer_unknown = self._footer_unknown
            self._project._id_to_name = self._id_to_name
        return self._project

    def populate_region_map(self):
        self._cur.execute(
            "SELECT comp_name, object_id, parent_id, record FROM comps WHERE parent_id=0 AND comp_name='Region Map'"
        )
        results = self._cur.fetchall()

        if len(results) == 0:
            return
        record = results[0][3]

        identifier_offset = 70

        if len(record) < (identifier_offset + 8):
            return

        region_length = struct.unpack(
            "I", record[identifier_offset + 4 : identifier_offset + 8]
        )[0]

        identifier_offset = 78
        record_length_absolute = identifier_offset + region_length - 4
        c = 0
        while identifier_offset <= (record_length_absolute - 16):
            parent_id_identifier = struct.unpack(
                "I", record[identifier_offset : identifier_offset + 4]
            )[0]

            unknown_identifier = struct.unpack(
                "I", record[identifier_offset + 4 : identifier_offset + 8]
            )[0]

            seq_identifier = struct.unpack(
                "I", record[identifier_offset + 8 : identifier_offset + 12]
            )[0]

            c += 1
            object_id_identifier = struct.unpack(
                "I", record[identifier_offset + 12 : identifier_offset + 16]
            )[0]

            query: str = "INSERT INTO region_map VALUES (?, ?, ?, ?, ?)"
            enty: tuple = (
                object_id_identifier,
                parent_id_identifier,
                unknown_identifier,
                seq_identifier,
                record[identifier_offset : identifier_offset + 16],
            )
            self._cur.execute(query, enty)
            identifier_offset += 16

        self._db.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Read an ACD file and export the database as an L5X file"
    )
    parser.add_argument(
        "input", metavar="input", type=str, nargs="+", help="The file to be converted"
    )
    parser.add_argument(
        "output",
        metavar="output",
        type=str,
        nargs="+",
        help="Filename of the exported file",
    )

    args = parser.parse_args()
    ExportL5x(args.input[0], args.output[0])
