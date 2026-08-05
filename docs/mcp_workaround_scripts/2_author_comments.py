# -*- coding: utf-8 -*-
"""
STEP 2 of the comment-authoring workaround.

Purpose: author a PROPOSED_DESCRIPTION for every `to_resolve` escalation in the
work packet, derived from the ladder logic captured in each item's rung
references (reviewed via step 1's dumps), then merge with the evidence-backed
`auto_decisions` into a single decision list.

This is the file that actually produced the ModernTHAWROOM021722 comments:
  - EXPLICIT{}  = hand-authored, logic-derived text for the semantic operands
                  (glycol pump, cell temp control, setpoints, scaling registers)
  - fan_desc()  = pattern generator for the two regular fan routines (120 items)
  - SCALE_MAP   = raw analog channel -> scratch reg -> scaled register mapping

Coverage is asserted: if any to_resolve NAME is left without a description the
script exits non-zero and lists the misses (nothing was hand-typed per item, so
a schema change upstream is caught immediately).

Input : <deliverables>/work_packet.json
Output: ./decisions.authored.json   (auto_decisions + authored drafts; 229 rows)

Run with any Python 3.8+ (no third-party deps).
"""
import json, re, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
DELIVERABLES = os.path.dirname(HERE)
WP = os.path.join(DELIVERABLES, "work_packet.json")
OUT = os.path.join(HERE, "decisions.authored.json")

d = json.load(open(WP, encoding="utf-8"))
auto = d["auto_decisions"]
to_resolve = d["to_resolve"]

# ---- explicit, logic-derived descriptions (semantic operands/tags) ----
# Confidence: HIGH = rung comment / direct output mapping; MEDIUM = inferred from comparison/latch role
EXPLICIT = {}

def add(name, desc, conf="MEDIUM", rat=""):
    EXPLICIT[name] = {"desc": desc, "conf": conf, "rat": rat}

# ---------- MainRoutine: JSR subroutine name tags ----------
add("Cell_1_Temperature_Control_4", "Cell 1 temperature-control subroutine \u2013 sequences Cell 1 glycol heating and ammonia cooling from product/room temperatures and setpoint deadbands.", "HIGH", "JSR in MainRoutine R2")
add("Cell_2_Temperature_Control_8", "Cell 2 temperature-control subroutine \u2013 sequences Cell 2 glycol heating and ammonia cooling from product/room temperatures and setpoint deadbands.", "HIGH", "JSR in MainRoutine R4")
add("Fan_01_10_Control_11", "Fan 01\u201310 control subroutine \u2013 commands circulation-fan drives 01\u201310 and collects EtherNet/IP drive feedback.", "HIGH", "JSR in MainRoutine R5")
add("Fan_11_20_Control_7", "Fan 11\u201320 control subroutine \u2013 commands circulation-fan drives 11\u201320 and collects EtherNet/IP drive feedback.", "HIGH", "JSR in MainRoutine R3")
add("Glycol_Pump_Control_12", "Glycol pump control subroutine \u2013 coordinates glycol-pump demand, all-valves-off permissive, run command, and the two pump outputs.", "HIGH", "JSR in MainRoutine R6")
add("Temperature_Input_Scaling_3", "Temperature input-scaling subroutine \u2013 scales the thaw-room RTD and meat-probe analog inputs into engineering-unit registers.", "HIGH", "JSR in MainRoutine R1")

# ---------- Glycol_Pump_Control_12 ----------
add("B3[0].0", "Glycol pump run request/seal \u2013 latched by glycol start command (N101[20].11) and sealed in; dropped by stop command (N101[20].12). Drives the glycol pump start/stop demand rungs.", "MEDIUM", "Glycol_Pump R0 seal, R1/R2 demand")
add("B3[0].1", "Glycol valve-off permissive \u2013 ON only when all six implemented Cell 1/Cell 2 glycol solenoid outputs (O:08.01\u201308.06) are de-energized; gates the glycol pump stop demand.", "HIGH", "Glycol_Pump R3 rung comment")
add("ENETBRIDGE_5069:8:O.Pt08.Data", "Glycol pump No. 1 output (O:08.09) \u2013 energized together with pump No. 2 while the glycol pump run command (N101[20].13) is latched.", "HIGH", "Glycol_Pump R4 rung comment")
add("ENETBRIDGE_5069:8:O.Pt09.Data", "Glycol pump No. 2 output (O:08.10) \u2013 energized together with pump No. 1 while the glycol pump run command (N101[20].13) is latched.", "HIGH", "Glycol_Pump R4 rung comment")
add("M0_1[37].0", "Glycol pump start-demand status flag \u2013 set with the glycol pump start-demand rung (mirrors run-command latch N101[20].13).", "MEDIUM", "Glycol_Pump R1")
add("M0_1[37].1", "Glycol pump stop-demand status flag \u2013 set with the glycol pump stop-demand rung.", "MEDIUM", "Glycol_Pump R2")
add("N101[20].11", "Glycol pump start command \u2013 initiates the glycol pump run request (B3[0].0).", "MEDIUM", "Glycol_Pump R0")
add("N101[20].12", "Glycol pump stop command \u2013 drops the glycol pump run request (B3[0].0).", "MEDIUM", "Glycol_Pump R0")
add("N101[20].13", "Glycol pump run command \u2013 latched by the start-demand rung and unlatched by the stop-demand rung; energizes glycol pump outputs O:08.09/O:08.10.", "HIGH", "Glycol_Pump R1/R2/R4")

# ---------- Cell 1 (N101 state, product temp N104[18], room temp N101[18]) ----------
add("ENETBRIDGE_5069:8:O.Pt00.Data", "Cell 1 glycol heating solenoid 1-A output (O:08.01) \u2013 admits warm glycol for Cell 1 heating when the heating branch is satisfied.", "HIGH", "Cell_1 R7 rung comment")
add("ENETBRIDGE_5069:8:O.Pt01.Data", "Cell 1 glycol heating solenoid 1-B output (O:08.02) \u2013 admits warm glycol for Cell 1 heating when the heating branch is satisfied.", "HIGH", "Cell_1 R7 rung comment")
add("ENETBRIDGE_5069:8:O.Pt02.Data", "Cell 1 glycol heating solenoid 1-C output (O:08.03) \u2013 admits warm glycol for Cell 1 heating when the heating branch is satisfied.", "HIGH", "Cell_1 R7 rung comment")
add("ENETBRIDGE_5069:8:O.Pt06.Data", "Cell 1 ammonia cooling solenoid output (O:08.07 \u2013 Thawing Room 1 ammonia sol) \u2013 energized to cool Cell 1 when the cooling branch is satisfied.", "HIGH", "Cell_1 R10 rung comment")
add("N101[20].3", "Cell 1 cooling demand/enable bit \u2013 one of the parallel branches that commands the Cell 1 ammonia solenoid (with room-temperature cooling inhibit N101[4].1).", "MEDIUM", "Cell_1 R10 branch")
add("N101[21].11", "Cell 1 start command \u2013 latches the Cell 1 run state (N101[20].1) ON.", "MEDIUM", "Cell_1 R0 OTL")
add("N101[21].12", "Cell 1 stop command \u2013 unlatches the Cell 1 run state (N101[20].1) OFF.", "MEDIUM", "Cell_1 R1 OTU")
add("N101[21].9", "Cell 1 operator cooling ON command \u2013 latches the operator cooling command (N101[21].5).", "HIGH", "Cell_1 R2 rung comment")
add("N101[21].10", "Cell 1 operator cooling OFF command \u2013 unlatches the operator cooling command (N101[21].5).", "MEDIUM", "Cell_1 R3 OTU")
add("N101[21].5", "Cell 1 operator cooling command latch \u2013 when set, enables the Cell 1 ammonia cooling branch.", "HIGH", "Cell_1 R2 rung comment")
add("N101[21].13", "Cell 1 operator heating ON command \u2013 latches the operator heating command (N101[21].15).", "HIGH", "Cell_1 R4 rung comment")
add("N101[21].14", "Cell 1 operator heating OFF command \u2013 unlatches the operator heating command (N101[21].15).", "MEDIUM", "Cell_1 R5 OTU")
add("N101[21].15", "Cell 1 operator heating command latch \u2013 when set, enables the Cell 1 glycol heating branch.", "HIGH", "Cell_1 R4 rung comment")
add("N101[4].0", "Cell 1 room-temperature heating-inhibit flag \u2013 set when room temperature (N101[18]) exceeds the room setpoint (N101[19]); blocks Cell 1 glycol heating.", "MEDIUM", "Cell_1 R8 GT, R7 XIO")
add("N101[4].1", "Cell 1 room-temperature cooling-inhibit flag \u2013 set when room temperature (N101[18]) is below the room setpoint (N101[19]); blocks Cell 1 ammonia cooling.", "MEDIUM", "Cell_1 R11 LT, R10 XIO")

# ---------- Cell 2 (N104 state, product/room temp N109[18]) ----------
add("ENETBRIDGE_5069:8:O.Pt03.Data", "Cell 2 glycol heating solenoid 2-A output (O:08.04) \u2013 admits warm glycol for Cell 2 heating when the heating branch is satisfied.", "HIGH", "Cell_2 R7 rung comment")
add("ENETBRIDGE_5069:8:O.Pt04.Data", "Cell 2 glycol heating solenoid 2-B output (O:08.05) \u2013 admits warm glycol for Cell 2 heating when the heating branch is satisfied.", "HIGH", "Cell_2 R7 rung comment")
add("ENETBRIDGE_5069:8:O.Pt05.Data", "Cell 2 glycol heating solenoid 2-C output (O:08.06) \u2013 admits warm glycol for Cell 2 heating when the heating branch is satisfied.", "HIGH", "Cell_2 R7 rung comment")
add("ENETBRIDGE_5069:8:O.Pt07.Data", "Cell 2 ammonia cooling solenoid output (O:08.08 \u2013 Thawing Room 2 ammonia sol) \u2013 energized to cool Cell 2 when the cooling branch is satisfied.", "HIGH", "Cell_2 R10 rung comment")
add("N104[20].3", "Cell 2 cooling demand/enable bit \u2013 one of the parallel branches that commands the Cell 2 ammonia solenoid (with room-temperature cooling inhibit N104[4].1).", "MEDIUM", "Cell_2 R10 branch")
add("N104[21].11", "Cell 2 start command \u2013 latches the Cell 2 run state (N104[20].1) ON.", "MEDIUM", "Cell_2 R0 OTL")
add("N104[21].12", "Cell 2 stop command \u2013 unlatches the Cell 2 run state (N104[20].1) OFF.", "MEDIUM", "Cell_2 R1 OTU")
add("N104[21].9", "Cell 2 operator cooling ON command \u2013 latches the operator cooling command (N104[21].5).", "HIGH", "Cell_2 R2 rung comment")
add("N104[21].10", "Cell 2 operator cooling OFF command \u2013 unlatches the operator cooling command (N104[21].5).", "MEDIUM", "Cell_2 R3 OTU")
add("N104[21].5", "Cell 2 operator cooling command latch \u2013 when set, enables the Cell 2 ammonia cooling branch.", "HIGH", "Cell_2 R2 rung comment")
add("N104[21].13", "Cell 2 operator heating ON command \u2013 latches the operator heating command (N104[21].15).", "HIGH", "Cell_2 R4 rung comment")
add("N104[21].14", "Cell 2 operator heating OFF command \u2013 unlatches the operator heating command (N104[21].15).", "MEDIUM", "Cell_2 R5 OTU")
add("N104[21].15", "Cell 2 operator heating command latch \u2013 when set, enables the Cell 2 glycol heating branch.", "HIGH", "Cell_2 R4 rung comment")
add("N104[4].0", "Cell 2 room-temperature heating-inhibit flag \u2013 set when room/product temperature (N109[18]) exceeds the room setpoint (N104[19]); blocks Cell 2 glycol heating.", "MEDIUM", "Cell_2 R8 GT, R7 XIO")
add("N104[4].1", "Cell 2 room-temperature cooling-inhibit flag \u2013 set when room/product temperature (N109[18]) is below the room setpoint (N104[19]); blocks Cell 2 ammonia cooling.", "MEDIUM", "Cell_2 R11 LT, R10 XIO")

# ---------- Setpoint / temperature registers (no direct comment; inferred from comparisons) ----------
add("N101[0]", "Cell 1 product low-temperature (heating) setpoint \u2013 glycol heating is enabled while product temperature (N104[18]) is below this value.", "MEDIUM", "Cell_1 R7 LT(N104[18],N101[0])")
add("N101[2]", "Cell 1 product high-temperature (cooling) setpoint \u2013 ammonia cooling is enabled while product temperature (N104[18]) is at or above this value.", "MEDIUM", "Cell_1 R10 GE(N104[18],N101[2])")
add("N101[19]", "Cell 1 room-temperature inhibit setpoint \u2013 compared against room temperature (N101[18]) to set the heating/cooling inhibit flags N101[4].0/.1.", "MEDIUM", "Cell_1 R8/R11")
add("N104[0]", "Cell 2 product low-temperature (heating) setpoint \u2013 glycol heating is enabled while product temperature (N109[18]) is below this value.", "MEDIUM", "Cell_2 R7 LT(N109[18],N104[0])")
add("N104[2]", "Cell 2 product high-temperature (cooling) setpoint \u2013 ammonia cooling is enabled while product temperature (N109[18]) is at or above this value.", "MEDIUM", "Cell_2 R10 GE(N109[18],N104[2])")
add("N104[19]", "Cell 2 room-temperature inhibit setpoint \u2013 compared against temperature (N109[18]) to set the heating/cooling inhibit flags N104[4].0/.1.", "MEDIUM", "Cell_2 R8/R11")

# ---------- Temperature_Input_Scaling_3 : raw channel -> scratch N18[x] -> stored N1yy[18] ----------
# mapping raw analog input -> (scratch, stored)
SCALE_MAP = {
    "ENETBRIDGE_5069:2:I.Ch02.Data": ("N18[11]", "N111[18]"),
    "ENETBRIDGE_5069:2:I.Ch03.Data": ("N18[12]", "N112[18]"),
    "ENETBRIDGE_5069:2:I.Ch04.Data": ("N18[13]", "N113[18]"),
    "ENETBRIDGE_5069:2:I.Ch05.Data": ("N18[14]", "N114[18]"),
    "ENETBRIDGE_5069:2:I.Ch06.Data": ("N18[15]", "N115[18]"),
    "ENETBRIDGE_5069:2:I.Ch07.Data": ("N18[16]", "N116[18]"),
    "ENETBRIDGE_5069:4:I.Ch02.Data": ("N18[27]", "N127[18]"),
    "ENETBRIDGE_5069:4:I.Ch03.Data": ("N18[28]", "N128[18]"),
    "ENETBRIDGE_5069:4:I.Ch04.Data": ("N18[29]", "N129[18]"),
    "ENETBRIDGE_5069:4:I.Ch05.Data": ("N18[30]", "N130[18]"),
    "ENETBRIDGE_5069:4:I.Ch06.Data": ("N18[31]", "N131[18]"),
    "ENETBRIDGE_5069:4:I.Ch07.Data": ("N18[32]", "N132[18]"),
}
for raw, (scr, sto) in SCALE_MAP.items():
    m = re.search(r":(\d+):I\.Ch(\d+)\.Data", raw)
    mod, ch = m.group(1), m.group(2)
    add(raw, "Raw RTD/meat-probe analog input (5069 module :%s Ch%s) \u2013 copied to scratch %s and stored as thaw-room temperature %s (engineering units)." % (mod, ch, scr, sto), "MEDIUM", "Temperature_Input_Scaling MOVE chain")
    add(scr, "Scratch register holding the raw module :%s Ch%s analog input during temperature scaling (source moved to %s)." % (mod, ch, sto), "MEDIUM", "Temperature_Input_Scaling MOVE chain")
    add(sto, "Scaled thaw-room temperature (engineering units) derived from module :%s Ch%s analog input via scratch %s." % (mod, ch, scr), "MEDIUM", "Temperature_Input_Scaling MOVE chain")

# ---------- Fan routines : regular pattern ----------
FAN_ENABLE = {"Fan_01_10_Control_11": "N104[20].1", "Fan_11_20_Control_7": "N101[20].1"}

def fan_desc(name, routine):
    grp = "01\u201310" if "01_10" in routine else "11\u201320"
    en = FAN_ENABLE[routine]
    m = re.match(r"Fan(\d+)_", name)
    n = m.group(1) if m else "?"
    if name.endswith("_DriveStatus"):
        return ("Fan %s PowerFlex drive status word \u2013 EtherNet/IP drive status feedback copied to this controller tag." % n, "HIGH", "%s R DRIVE FEEDBACK" % routine)
    if name.endswith("_SpeedFeedback"):
        return ("Fan %s speed feedback \u2013 drive output frequency copied from the PowerFlex EtherNet/IP input." % n, "HIGH", "%s MOVE OutputFreq" % routine)
    if name.endswith("_EIP:I.DriveStatus"):
        return ("Fan %s PowerFlex drive status feedback (EtherNet/IP input) \u2013 copied to Fan%s_DriveStatus." % (n, n), "HIGH", "%s DRIVE FEEDBACK" % routine)
    if name.endswith("_EIP:I.OutputFreq"):
        return ("Fan %s PowerFlex drive output-frequency feedback (EtherNet/IP input) \u2013 copied to Fan%s_SpeedFeedback." % (n, n), "HIGH", "%s MOVE OutputFreq" % routine)
    if name.endswith("_EIP:O.Start"):
        return ("Fan %s PowerFlex drive start command \u2013 energized with the Fan %s group while the fan run enable (%s) is ON." % (n, grp, en), "HIGH", "%s R1" % routine)
    if name.endswith("_EIP:O.Stop"):
        return ("Fan %s PowerFlex drive stop command \u2013 energized with the Fan %s group while the fan run enable (%s) is OFF." % (n, grp, en), "HIGH", "%s R0" % routine)
    return None

add("M0_1[42].0", "Fan 01\u201310 group stop status flag \u2013 set with the Fan 01\u201310 stop commands while the fan run enable (N104[20].1) is OFF.", "MEDIUM", "Fan_01_10 R0")
add("M0_1[42].1", "Fan 01\u201310 group start status flag \u2013 set with the Fan 01\u201310 start commands while the fan run enable (N104[20].1) is ON.", "MEDIUM", "Fan_01_10 R1")

# ---- build decisions for every to_resolve item ----
decisions = []
missing = []
for it in to_resolve:
    dd = dict(it["draft_decision"])  # keeps TYPE/SCOPE/NAME/STATUS
    name = dd["NAME"]
    rr = it.get("rung_references", [])
    routine = rr[0]["routine"] if rr else None
    desc = conf = rat = None
    if name in EXPLICIT:
        e = EXPLICIT[name]; desc, conf, rat = e["desc"], e["conf"], e["rat"]
    elif routine in FAN_ENABLE:
        fd = fan_desc(name, routine)
        if fd: desc, conf, rat = fd
    if desc is None:
        missing.append(name)
        continue
    dd["PROPOSED_DESCRIPTION"] = desc
    dd["CONFIDENCE"] = conf
    dd["STATUS"] = "inferred"
    dd["RATIONALE"] = rat
    decisions.append(dd)

if missing:
    print("MISSING (%d):" % len(missing))
    for m in missing: print("  ", m)
    sys.exit(1)

# ---- append auto_decisions (evidence-backed, pass through unchanged) ----
combined = decisions + auto

# sanity: no duplicate NAMEs across our authored set
names = [x["NAME"] for x in decisions]
dups = set(n for n in names if names.count(n) > 1)
print("authored:", len(decisions), " auto:", len(auto), " combined:", len(combined))
print("authored dup names:", dups if dups else "none")

json.dump(combined, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("wrote", OUT)
