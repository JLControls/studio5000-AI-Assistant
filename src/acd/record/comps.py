from dataclasses import dataclass
from io import BytesIO
from sqlite3 import Cursor
from typing import Optional

import kaitaistruct
from acd.database.dbextract import DatRecord
from kaitaistruct import EndOfStreamError, KaitaiStream
from loguru import logger

from acd.generated.comps.fafa_comps import FafaComps
from acd.generated.comps.fdfd_comps import FdfdComps


@dataclass
class RecordData:
    object_id: int
    record_length: int
    seq_number: int
    record_type: int
    dat_record: DatRecord


@dataclass
class CompsRecord:
    _cur: Cursor
    dat_record: DatRecord

    def __post_init__(self):
        entry = CompsRecord.parse(self.dat_record)
        if entry is None:
            return
        self._cur.execute(f"DELETE FROM comps WHERE object_id={entry[0]}")
        self._cur.execute("INSERT INTO comps VALUES (?, ?, ?, ?, ?, ?)", entry)

    @staticmethod
    def parse(dat_record: DatRecord) -> Optional[tuple]:
        try:
            if dat_record.identifier == 64250:
                r = FafaComps.from_bytes(dat_record.record.record_buffer)
            elif dat_record.identifier == 65021:
                r = FdfdComps(
                    dat_record.len_record,
                    KaitaiStream(BytesIO(dat_record.record.record_buffer)),
                )
            else:
                return None
            return (
                r.header.object_id,
                r.header.parent_id,
                r.header.record_name.value,
                r.header.seq_number,
                r.header.record_type,
                r.record_buffer,
            )
        except (EndOfStreamError, kaitaistruct.ValidationNotEqualError) as e:
            # Source-protected (encrypted) content stores comps records whose
            # body is ciphertext: the record-name field is high-entropy noise
            # with no UTF-16 terminator, so the lazy header parse runs off the
            # end of its substream. Nothing offline can decrypt these; skip
            # the record instead of aborting the whole conversion.
            logger.debug(
                "Skipping unparseable comps record "
                f"(identifier={dat_record.identifier}, "
                f"len={dat_record.len_record}): {type(e).__name__}: {e}"
            )
            return None
