from flask import Blueprint, jsonify, request
from flask_login import login_required
from app.models import Equipment, EquipmentParam

api_bp = Blueprint("api", __name__)


@api_bp.route("/equipment")
@login_required
def get_equipment():
    dept_id = request.args.get("dept_id", type=int)
    if not dept_id:
        return jsonify([])
    items = Equipment.query.filter_by(dept_id=dept_id, is_active=True).order_by(Equipment.name).all()
    return jsonify([{"id": e.id, "name": e.name} for e in items])


@api_bp.route("/params")
@login_required
def get_params():
    equipment_id = request.args.get("equipment_id", type=int)
    if not equipment_id:
        return jsonify([])
    params = (
        EquipmentParam.query
        .filter_by(equipment_id=equipment_id)
        .order_by(EquipmentParam.display_order)
        .all()
    )
    return jsonify([
        {"param_name": p.param_name, "unit": p.unit or "", "section": p.section or ""}
        for p in params
    ])
