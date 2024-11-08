# votaciones_uniacme/models/models.py
from odoo import api, exceptions, fields, models, _
from odoo.exceptions import ValidationError
import base64
import csv
from io import StringIO


class UniversityCampus(models.Model):
    _name = 'university.campus'
    _description = 'University Campus'

    name = fields.Char(string='Nombre de la Sede', required=True)
    country = fields.Char(string='Ubicación')
    timezone = fields.Selection([
        ('UTC', 'UTC'),
        ('GMT-5', 'GMT-5'),
        ('GMT-3', 'GMT-3'),
        ('CET', 'CET'),
    ], string='Zona Horaria', required=True)

class UniversityStudent(models.Model):
    _name = "university.student"
    _description = "University Student"

    name = fields.Char(string='Nombre del Estudiante', required=True) 
    sede_id = fields.Many2one('university.campus', string='Sede', required=True)
    identificacion = fields.Integer(string='Identificación', required=True)
    carrera = fields.Char(string='Carrera', required=True)

    _sql_constraints = [
        ('identificacion_unique', 'unique(identificacion)', 'La identificación debe ser única para cada estudiante.')
    ]

    @api.model
    def create(self, vals):
        # Evita que el campo identificación se guarde con valor 0
        if 'identificacion' in vals and vals['identificacion'] == 0:
            vals['identificacion'] = None
        return super(UniversityStudent, self).create(vals)

class Candidate(models.Model):
    _name = 'votaciones.candidate'
    _inherits = {'university.student': 'student_id'}
    _description = 'Candidatos para la Votación'

    student_id = fields.Many2one('university.student', ondelete="cascade", required=True)
    votes_count = fields.Integer(string='Cantidad de Votos', default=0)

    def increment_vote_count(self):
        self.sudo().write({'votes_count': self.votes_count + 1})

class VotingProcess(models.Model):
    _name = 'university.voting'
    _description = 'Proceso de Votación'

    name = fields.Char('Nombre del proceso', required=True, translate=True)
    description = fields.Text(string='Descripción de la Votación', required=True)
    start_datetime = fields.Datetime(string='Fecha y Hora de Inicio', required=True)
    end_datetime = fields.Datetime(string='Fecha y Hora de Fin', required=True)
    sede_id = fields.Many2one('university.campus', string='Sede')
    candidates_ids = fields.Many2many('votaciones.candidate', string='Candidatos')
    state = fields.Selection([('draft', 'Borrador'), ('active', 'En Proceso'), ('closed', 'Cerrada')], 
                             string='Estado', default='draft')
    student_ids = fields.Many2many('university.student', string='Estudiantes que han votado')


    def start_voting(self):
        """Método para iniciar la votación (cambiar estado a 'En Proceso')."""
        self.state = 'active'

        
class VotingStudent(models.Model):
    _name = 'voting.student'
    _description = 'Proceso de Votación para Estudiantes'

    voting_process_id = fields.Many2one(
        'university.voting', string='Proceso de Votación', required=True,
        domain="[('state', '=', 'active')]"  # Solo votaciones "En Proceso"
    )

    candidate_id = fields.Many2one('votaciones.candidate', string='Candidato', required=True)
    student_id = fields.Many2one(  # Many2one para seleccionar el estudiante manualmente
        'university.student', string='Estudiante', required=True, 
        ondelete='restrict'  # Evita la eliminación del estudiante si está vinculado a un voto
    )

    @api.model
    def create(self, vals):
        # Verificar que el estudiante esté seleccionado y sea válido
        student_id = vals.get('student_id')
        if student_id:
            student = self.env['university.student'].browse(student_id)
            if not student.exists():
                raise ValidationError(_('El estudiante seleccionado no es válido.'))
        return super(VotingStudent, self).create(vals)

    def cast_vote(self):
        """Permite que el estudiante emita su voto para un candidato específico"""

        # Verifica que el estudiante_id haya sido asignado correctamente
        if not self.student_id:
            raise ValidationError(_('Debe seleccionar un estudiante para registrar el voto.'))

        # Verifica si el estudiante ya votó en este proceso de votación
        if self.voting_process_id.student_ids.filtered(lambda s: s.id == self.student_id.id):
            raise ValidationError(_('Este estudiante ya ha votado en este proceso de votación.'))

        # Incrementa el contador de votos del candidato
        self.candidate_id.increment_vote_count()

        # Registra que el estudiante ha votado en este proceso, agregándolo a la lista de votantes
        self.voting_process_id.write({'student_ids': [(4, self.student_id.id)]})

        # Registra el voto en el modelo voting.student
        existing_vote = self.env['voting.student'].search([
            ('voting_process_id', '=', self.voting_process_id.id),
            ('student_id', '=', self.student_id.id)
        ], limit=1)
    
        if not existing_vote:
            self.write({'student_id': self.student_id.id})

class VotingProcessImportWizard(models.TransientModel):
    _name = 'votaciones.import.wizard'
    _description = 'Wizard de Importación de Procesos de Votación'

    file = fields.Binary(string='Archivo CSV', required=True)
    filename = fields.Char(string='Nombre del archivo')

    def action_import_processes(self):
        """Importa los procesos de votación desde el archivo CSV y los guarda en estado 'borrador'."""
        if not self.file:
            raise ValidationError('Por favor, cargue un archivo CSV.')

        # Decodificar el archivo
        file_data = base64.b64decode(self.file)
        file_content = StringIO(file_data.decode("utf-8"))
        reader = csv.DictReader(file_content)

        for row in reader:
            # Validar que los campos necesarios estén presentes
            if not all(key in row for key in ['name', 'description', 'start_datetime', 'end_datetime', 'sede_id']):
                raise ValidationError('El archivo debe contener todos los campos necesarios.')

            # Crear el proceso de votación
            self.env['university.voting'].create({
                'name': row['name'],
                'description': row['description'],
                'start_datetime': row['start_datetime'],
                'end_datetime': row['end_datetime'],
                'sede_id': row['sede_id'],
                'state': 'draft',
            })
    
    def action_download_template(self):
        """Genera una plantilla CSV para la importación."""
        template_data = "name,description,start_datetime,end_datetime,sede_id\n"
        template_data += "Proceso de Votación 1,Descripción del proceso,2024-11-01 09:00:00,2024-11-01 18:00:00,1\n"
        
        # Codificar la plantilla a base64
        file_data = base64.b64encode(template_data.encode("utf-8"))
        self.write({
            'file': file_data,
            'filename': 'template_votaciones.csv'
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'votaciones.import.wizard',
            'view_mode': 'form',
            'view_id': False,
            'target': 'new',
            'res_id': self.id,
        }