import os
import secrets
from datetime import date
from decimal import Decimal

import click
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_admin.form import SecureForm
from flask_babel import Babel
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_uploads import IMAGES, UploadNotAllowed, UploadSet, configure_uploads
from sqlalchemy import CheckConstraint, UniqueConstraint, event, func, select
from sqlalchemy.exc import IntegrityError
from wtforms import BooleanField, DateField, DecimalField, FileField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from werkzeug.security import generate_password_hash
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional, ValidationError


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "mysql+pymysql://root@localhost:3306/scol"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["BABEL_DEFAULT_LOCALE"] = "fr"
app.config["UPLOADED_PHOTOS_DEST"] = os.path.join(app.root_path, "static", "image")
db = SQLAlchemy(app)
migrate = Migrate(app, db)
babel = Babel(app)
photos = UploadSet("photos", IMAGES)
configure_uploads(app, photos)


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    def __str__(self):
        return self.username


class Classe(db.Model):
    __tablename__ = "classe"
    __table_args__ = (CheckConstraint("NbrEtud >= 0"),)

    CodClass = db.Column(db.String(20), primary_key=True)
    NomClass = db.Column(db.String(80), unique=True, nullable=False)
    NbrEtud = db.Column(db.Integer, nullable=False, default=0)
    etudiants = db.relationship("Etudiant", back_populates="classe", cascade="all, delete-orphan")

    def __str__(self):
        return self.NomClass


class Etudiant(db.Model):
    __tablename__ = "etudiant"

    NCE = db.Column(db.String(20), primary_key=True)
    Nom = db.Column(db.String(80), nullable=False)
    Prenom = db.Column(db.String(80), nullable=False)
    DateNais = db.Column(db.Date, nullable=False)
    LieuNais = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.TIMESTAMP, server_default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )
    photo = db.Column(db.String(255))
    CodClass = db.Column(
        db.String(20),
        db.ForeignKey("classe.CodClass", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    classe = db.relationship("Classe", back_populates="etudiants")
    absences = db.relationship("Absence", back_populates="etudiant", cascade="all, delete-orphan")

    def __str__(self):
        return f"{self.Nom} {self.Prenom}"


class Matiere(db.Model):
    __tablename__ = "matiere"

    CodMat = db.Column(db.String(20), primary_key=True)
    IntMat = db.Column(db.String(100), nullable=False)
    Description = db.Column(db.Text, nullable=False, default="")
    absences = db.relationship("Absence", back_populates="matiere", cascade="all, delete-orphan")

    def __str__(self):
        return self.IntMat


class Absence(db.Model):
    __tablename__ = "absence"
    __table_args__ = (
        CheckConstraint("NHA > 0"),
        UniqueConstraint("CodMat", "NCE", "DateA"),
    )

    id = db.Column(db.Integer, primary_key=True)
    CodMat = db.Column(
        db.String(20),
        db.ForeignKey("matiere.CodMat", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    NCE = db.Column(
        db.String(20),
        db.ForeignKey("etudiant.NCE", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    DateA = db.Column(db.Date, nullable=False)
    NHA = db.Column(db.Numeric(5, 2), nullable=False)
    matiere = db.relationship("Matiere", back_populates="absences")
    etudiant = db.relationship("Etudiant", back_populates="absences")


@event.listens_for(Etudiant, "after_insert")
@event.listens_for(Etudiant, "after_update")
@event.listens_for(Etudiant, "after_delete")
def recalculer_effectifs(mapper, connection, etudiant):
    effectif = (
        select(func.count())
        .select_from(Etudiant)
        .where(Etudiant.CodClass == Classe.CodClass)
        .scalar_subquery()
    )
    connection.execute(
        Classe.__table__.update().values(NbrEtud=effectif)
    )


class UserForm(FlaskForm):
    username = StringField("Nom d'utilisateur", validators=[DataRequired(), Length(min=4, max=20)])
    email = StringField("Adresse e-mail", validators=[DataRequired(), Email(), Length(max=200)])
    password = PasswordField("Mot de passe", validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Ajouter")

    def populate_obj(self, obj):
        obj.username = self.username.data.strip()
        obj.email = self.email.data.strip().lower()


class ClasseForm(FlaskForm):
    CodClass = StringField("Code classe", validators=[DataRequired(), Length(max=20)])
    NomClass = StringField("Nom de la classe", validators=[DataRequired(), Length(max=80)])
    submit = SubmitField("Ajouter")


class EtudiantForm(FlaskForm):
    NCE = StringField("Numéro de carte étudiant", validators=[DataRequired(), Length(max=20)])
    Nom = StringField("Nom", validators=[DataRequired(), Length(max=80)])
    Prenom = StringField("Prénom", validators=[DataRequired(), Length(max=80)])
    DateNais = DateField("Date de naissance", validators=[DataRequired()])
    LieuNais = StringField("Lieu de naissance", validators=[DataRequired(), Length(max=100)])
    CodClass = SelectField("Classe", validators=[DataRequired()])
    is_active = BooleanField("Actif")
    photo = FileField("Photo (PNG, JPG ou GIF)")
    submit = SubmitField("Ajouter")

    def validate_DateNais(self, field):
        if field.data > date.today():
            raise ValidationError("La date de naissance ne peut pas être dans le futur.")


class EtudiantEditForm(FlaskForm):
    Nom = StringField("Nom", validators=[DataRequired(), Length(max=80)])
    Prenom = StringField("Prénom", validators=[DataRequired(), Length(max=80)])
    DateNais = DateField("Date de naissance", validators=[DataRequired()])
    LieuNais = StringField("Lieu de naissance", validators=[DataRequired(), Length(max=100)])
    CodClass = SelectField("Classe", validators=[DataRequired()])
    is_active = BooleanField("Actif")
    photo = FileField("Nouvelle photo (PNG, JPG ou GIF)")
    submit = SubmitField("Enregistrer")

    def validate_DateNais(self, field):
        if field.data > date.today():
            raise ValidationError("La date de naissance ne peut pas être dans le futur.")


class DeleteEtudiantForm(FlaskForm):
    submit = SubmitField("Supprimer")


class MatiereForm(FlaskForm):
    CodMat = StringField("Code matière", validators=[DataRequired(), Length(max=20)])
    IntMat = StringField("Intitulé", validators=[DataRequired(), Length(max=100)])
    Description = TextAreaField("Description", validators=[Length(max=2000)])
    submit = SubmitField("Ajouter")


class AbsenceForm(FlaskForm):
    NCE = SelectField("Étudiant", validators=[DataRequired()])
    CodMat = SelectField("Matière", validators=[DataRequired()])
    DateA = DateField("Date d'absence", validators=[DataRequired()])
    NHA = DecimalField(
        "Nombre d'heures d'absence",
        places=2,
        validators=[DataRequired(), NumberRange(min=Decimal("0.01"), max=Decimal("999.99"))],
    )
    submit = SubmitField("Ajouter")

    def validate_NHA(self, field):
        if not field.data.is_finite():
            raise ValidationError("Saisissez un nombre fini.")
        if field.data.as_tuple().exponent < -2:
            raise ValidationError("Saisissez au maximum deux décimales.")


class UserAdmin(ModelView):
    form = UserForm
    form_base_class = SecureForm
    page_size = 5
    page_size_options = (5, 10, 20, 50, 100)
    can_set_page_size = True
    column_exclude_list = ["password"]

    def edit_form(self, obj=None):
        form = super().edit_form(obj)
        form.password.validators = [Optional(), Length(min=6)]
        return form

    def on_model_change(self, form, model, is_created):
        if form.password.data:
            model.password = generate_password_hash(form.password.data)


class ScolariteAdmin(ModelView):
    form_base_class = SecureForm


class ClassesAdmin(ScolariteAdmin):
    form_columns = ["CodClass", "NomClass"]
    column_list = ["CodClass", "NomClass", "NbrEtud"]


class EtudiantsAdmin(ScolariteAdmin):
    form_columns = ["NCE", "Nom", "Prenom", "DateNais", "LieuNais", "is_active", "photo", "classe"]
    column_list = ["NCE", "Nom", "Prenom", "DateNais", "LieuNais", "is_active", "photo", "classe"]
    form_extra_fields = {"photo": FileField("Photo (PNG, JPG ou GIF)")}

    def on_model_change(self, form, model, is_created):
        if model.DateNais > date.today():
            raise ValueError("La date de naissance ne peut pas être dans le futur.")
        fichier = form.photo.data
        if fichier and getattr(fichier, "filename", ""):
            model.photo = sauvegarder_photo(fichier)


class MatieresAdmin(ScolariteAdmin):
    form_columns = ["CodMat", "IntMat", "Description"]
    form_args = {"Description": {"validators": [Length(max=2000)]}}


class AbsencesAdmin(ScolariteAdmin):
    form_columns = ["matiere", "etudiant", "DateA", "NHA"]
    column_list = ["matiere", "etudiant", "DateA", "NHA"]
    form_args = {
        "NHA": {
            "places": 2,
            "validators": [
                DataRequired(),
                NumberRange(min=Decimal("0.01"), max=Decimal("999.99")),
                AbsenceForm.validate_NHA,
            ],
        },
    }


admin = Admin(app, index_view=AdminIndexView(name="Admin Panel"))
admin.add_view(UserAdmin(User, db.session))
admin.add_view(ClassesAdmin(Classe, db.session))
admin.add_view(EtudiantsAdmin(Etudiant, db.session))
admin.add_view(MatieresAdmin(Matiere, db.session))
admin.add_view(AbsencesAdmin(Absence, db.session))


def sauvegarder_photo(fichier):
    if not fichier or not getattr(fichier, "filename", ""):
        return None
    if not allowed_image(fichier.filename):
        raise UploadNotAllowed
    os.makedirs(app.config["UPLOADED_PHOTOS_DEST"], exist_ok=True)
    return photos.save(fichier)


def supprimer_photo(nom):
    if nom:
        if os.path.basename(nom) != nom:
            raise ValueError("Nom de photo invalide.")
        chemin = os.path.join(app.config["UPLOADED_PHOTOS_DEST"], nom)
        if os.path.isfile(chemin):
            os.remove(chemin)
        else:
            app.logger.warning("Photo d'étudiant introuvable : %s", nom)


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"png", "jpg", "jpeg", "gif"}


def enregistrer(objet, destination):
    db.session.add(objet)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        app.logger.warning("Insertion refusée : doublon ou référence invalide.", exc_info=True)
        flash("Enregistrement impossible : ce code, cet e-mail ou cette absence existe déjà, "
              "ou une référence n'est plus disponible.", "error")
        return None
    flash("Enregistrement ajouté.", "success")
    return redirect(url_for(destination))


@app.route("/")
def index():
    classes = db.session.scalars(select(Classe).order_by(Classe.NomClass)).all()
    return render_template("index.html", classes=classes)


@app.route("/students")
def students():
    etudiants = db.session.scalars(
        select(Etudiant).order_by(Etudiant.Nom, Etudiant.Prenom, Etudiant.NCE)
    ).all()
    return render_template("students.html", etudiants=etudiants, delete_form=DeleteEtudiantForm())


@app.route("/users/ajouter", methods=["GET", "POST"])
def ajouter_user():
    form = UserForm()
    if form.validate_on_submit():
        reponse = enregistrer(
            User(
                username=form.username.data.strip(),
                email=form.email.data.strip().lower(),
                password=generate_password_hash(form.password.data),
            ),
            "ajouter_user",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter un utilisateur", form=form)


@app.route("/classes/ajouter", methods=["GET", "POST"])
def ajouter_classe():
    form = ClasseForm()
    if form.validate_on_submit():
        reponse = enregistrer(
            Classe(CodClass=form.CodClass.data.strip(), NomClass=form.NomClass.data.strip()),
            "index",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter une classe", form=form)


@app.route("/addStudent/", methods=["GET", "POST"])
@app.route("/etudiants/ajouter", methods=["GET", "POST"])
def ajouter_etudiant():
    form = EtudiantForm()
    form.CodClass.choices = [
        (classe.CodClass, classe.NomClass)
        for classe in db.session.scalars(select(Classe).order_by(Classe.NomClass))
    ]
    if form.validate_on_submit():
        etudiant = Etudiant(
            NCE=form.NCE.data.strip(),
            Nom=form.Nom.data.strip(),
            Prenom=form.Prenom.data.strip(),
            DateNais=form.DateNais.data,
            LieuNais=form.LieuNais.data.strip(),
            CodClass=form.CodClass.data,
            is_active=form.is_active.data,
        )
        try:
            etudiant.photo = sauvegarder_photo(form.photo.data)
            reponse = enregistrer(etudiant, "students")
        except UploadNotAllowed:
            db.session.rollback()
            flash("Format de photo non autorisé. Choisissez une image PNG, JPG ou GIF.", "error")
            return render_template("formulaire.html", titre="Ajouter un étudiant", form=form)
        except OSError:
            db.session.rollback()
            app.logger.exception("Impossible de sauvegarder la photo de l'étudiant.")
            flash("Impossible de sauvegarder cette photo.", "error")
            return render_template("formulaire.html", titre="Ajouter un étudiant", form=form)
        if reponse is not None:
            return reponse
        if etudiant.photo:
            supprimer_photo(etudiant.photo)
    return render_template("formulaire.html", titre="Ajouter un étudiant", form=form)


@app.route("/editStudent/<string:student_nce>", methods=["GET", "POST"])
def edit_student(student_nce):
    etudiant = db.get_or_404(Etudiant, student_nce)
    form = EtudiantEditForm(obj=etudiant)
    form.CodClass.choices = [
        (classe.CodClass, classe.NomClass)
        for classe in db.session.scalars(select(Classe).order_by(Classe.NomClass))
    ]
    if form.validate_on_submit():
        ancienne_photo = etudiant.photo
        fichier = request.files.get("photo")
        nouvelle_photo = None
        try:
            if fichier and getattr(fichier, "filename", ""):
                nouvelle_photo = sauvegarder_photo(fichier)
            etudiant.Nom = form.Nom.data.strip()
            etudiant.Prenom = form.Prenom.data.strip()
            etudiant.DateNais = form.DateNais.data
            etudiant.LieuNais = form.LieuNais.data.strip()
            etudiant.CodClass = form.CodClass.data
            etudiant.is_active = form.is_active.data
            if nouvelle_photo:
                etudiant.photo = nouvelle_photo
            db.session.commit()
        except UploadNotAllowed:
            db.session.rollback()
            flash("Format de photo non autorisé. Choisissez une image PNG, JPG ou GIF.", "error")
        except IntegrityError:
            db.session.rollback()
            if nouvelle_photo:
                supprimer_photo(nouvelle_photo)
            app.logger.warning("Modification étudiant refusée par la base de données.", exc_info=True)
            flash("Modification impossible : la classe sélectionnée n'est plus disponible.", "error")
        except OSError:
            db.session.rollback()
            if nouvelle_photo:
                supprimer_photo(nouvelle_photo)
            app.logger.exception("Impossible de sauvegarder la photo de l'étudiant.")
            flash("Impossible de sauvegarder cette photo.", "error")
        else:
            if nouvelle_photo and ancienne_photo:
                supprimer_photo(ancienne_photo)
            flash("Étudiant modifié avec succès.", "success")
            return redirect(url_for("students"))
    return render_template("formulaire.html", titre="Modifier un étudiant", form=form, etudiant=etudiant)


@app.route("/deleteStudent/<string:student_nce>", methods=["POST"])
def delete_student(student_nce):
    form = DeleteEtudiantForm()
    if not form.validate_on_submit():
        abort(400, description="Jeton CSRF invalide.")
    etudiant = db.get_or_404(Etudiant, student_nce)
    photo = etudiant.photo
    try:
        db.session.delete(etudiant)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        app.logger.warning("Suppression étudiant refusée par la base de données.", exc_info=True)
        flash("Impossible de supprimer cet étudiant car il est lié à d'autres données.", "error")
    else:
        if photo:
            supprimer_photo(photo)
        flash("Étudiant supprimé avec succès.", "success")
    return redirect(url_for("students"))


@app.route("/matieres/ajouter", methods=["GET", "POST"])
def ajouter_matiere():
    form = MatiereForm()
    if form.validate_on_submit():
        reponse = enregistrer(
            Matiere(
                CodMat=form.CodMat.data.strip(),
                IntMat=form.IntMat.data.strip(),
                Description=form.Description.data.strip(),
            ),
            "ajouter_matiere",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter une matière", form=form)


@app.route("/absences/ajouter", methods=["GET", "POST"])
def ajouter_absence():
    form = AbsenceForm()
    form.NCE.choices = [
        (etudiant.NCE, f"{etudiant.NCE} - {etudiant.Nom} {etudiant.Prenom}")
        for etudiant in db.session.scalars(select(Etudiant).order_by(Etudiant.Nom, Etudiant.Prenom))
    ]
    form.CodMat.choices = [
        (matiere.CodMat, matiere.IntMat)
        for matiere in db.session.scalars(select(Matiere).order_by(Matiere.IntMat))
    ]
    if form.validate_on_submit():
        reponse = enregistrer(
            Absence(
                NCE=form.NCE.data,
                CodMat=form.CodMat.data,
                DateA=form.DateA.data,
                NHA=form.NHA.data,
            ),
            "index",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter une absence", form=form)


@app.route("/classes/<cod_class>/etudiants/<nce>/absences")
def absences_etudiant(cod_class, nce):
    etudiant = db.first_or_404(
        select(Etudiant).where(Etudiant.NCE == nce, Etudiant.CodClass == cod_class)
    )
    absences = db.session.scalars(
        select(Absence)
        .where(Absence.NCE == etudiant.NCE)
        .order_by(Absence.DateA, Absence.CodMat)
    ).all()
    return render_template("absece_Etudiant.html", etudiant=etudiant, absences=absences)


@app.cli.command("init-db")
def init_db():
    with app.app_context():
        db.create_all()
    click.echo("Les tables de la base scol ont été créées.")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")