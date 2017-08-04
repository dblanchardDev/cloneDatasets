# coding: utf-8 
'''CLONE DATASETS – David Blanchard – Esri Canada 2017
Creates new datasets (feature classes, tables, or relationship
classes plus domains) using existing datasets as templates'''

# All literal strings will be Unicode instead of bytes
from __future__ import unicode_literals

# Import modules
import arcpy

## IN-CODE PARAMETERS #################
params = {
	"datasets": [],
	"outGDB": r"",
	"overwrite": False
}
## END ################################



##MAIN CODE########################################################################################
def execute(datasetList, outGDB, overwrite):
	'''Run through and clone datasets'''
	arcpy.SetProgressor("step", None, 0, len(datasetList), 1)
	results = {"successes": 0, "failures": 0}
	
	# Loop through datasets
	relationshipClasses = []
	for dataset in datasetList:
		arcpy.SetProgressorLabel("Cloning {0}".format(dataset.split(".")[-1]))
		success = None
	
		try:
			desc = arcpy.Describe(dataset)
		
			# Feature classes
			if desc.dataType == "FeatureClass":
				success = cloneFeatureClass(desc, outGDB, overwrite)
		
			# Tables
			elif desc.dataType == "Table":
				success = cloneTables(desc, outGDB, overwrite)
		
			# Relationship Classes
			#(kept for last, ensuring related tables copied first)
			elif desc.dataType == "RelationshipClass":
				relationshipClasses.append(desc)
			
			# All other types are unsupported
			else:
				success = False
				arcpy.AddError("Dataset {0} is of an unsupported type ({1})".format(dataset, desc.dataType))

		except Exception:
			success = False
			arcpy.AddError("An error occurred while cloning {0}".format(dataset))
		
		if success is not None:
			arcpy.SetProgressorPosition()
			results["successes" if success else "failures"] += 1

	# Relationship Classes
	for desc in relationshipClasses:
		arcpy.SetProgressorLabel("Cloning {0}".format(desc.name.split(".")[-1]))
		success = None
		
		try:
			success = cloneRelationshipClass(desc, outGDB)
		except Exception:
			success = False
			arcpy.AddError("An error occurred while cloning the {0} relationship class".format(desc.name))
		
		arcpy.SetProgressorPosition()
		results["successes" if success else "failures"] += 1
	
	return results



##CLONING FUNCTIONS################################################################################

def cloneFeatureClass(desc, outGDB, overwrite):
	'''Clone a feature class (name, shape type, schema, and domains)'''
	success = True
	
	# Cannot clone FCs without a shape type
	if desc.shapeType == "Any":
		arcpy.AddError("Unable to clone {0} as the shape type is not defined".format(desc.name))
		success = False
	
	# Cannot clone non-simple feature classes
	elif not desc.featureType == "Simple":
		arcpy.AddError("Unable to clone {0} as it is not a simple feature class".format(desc.name))
	
	else:
		cloneDomains(desc, outGDB)
		
		# Translate properties to parameters
		name = desc.name.split(".")[-1]
		shape = desc.shapeType.upper()
		template = "{0}\\{1}".format(desc.path, desc.name)
		SAT = "SAME_AS_TEMPLATE"
		
		if existsOrReplace(outGDB, name, overwrite):
			arcpy.CreateFeatureclass_management(outGDB, name, shape, template, SAT, SAT, template)
			arcpy.AddMessage("Cloned Feature Class {0}".format(name))
	
	return success



def cloneTables(desc, outGDB, overwrite):
	'''Clone a GDB table (name, schema and domains)'''
	success = True
	
	cloneDomains(desc, outGDB)
	name = desc.name.split(".")[-1]
	template = "{0}\\{1}".format(desc.path, desc.name)
	
	if existsOrReplace(outGDB, name, overwrite):
		arcpy.CreateTable_management(outGDB, name, template)
		arcpy.AddMessage("Cloned Table {0}".format(name))
	
	return success



def cloneDomains(datasetDesc, outGDB):
	'''Clone all domains attached to a dataset and not yet present in output GDB'''
	
	# Get all domains in dataset not yet in output GDB
	missingDomains = []
	gdbDesc = arcpy.Describe(outGDB)
	
	for field in datasetDesc.fields:
		if field.domain and field.domain not in gdbDesc.domains and field.domain not in missingDomains:
			missingDomains.append(field.domain)
	
	# Add missing domains to output GDB
	if len(missingDomains) > 0:
		domainList = arcpy.da.ListDomains(datasetDesc.path) #pylint: disable=E1101
		
		for domainName in missingDomains:
			domain = [e for e in domainList if e.name == domainName][0]
			
			# Translate properties to parameters
			name = domain.name
			description = domain.description
			fieldType = domain.type.upper()
			domainType = {"CodedValue": "CODED", "Range": "RANGE"}[domain.domainType]
			splitPolicy = {"DefaultValue": "DEFAULT", "Duplicate": "DUPLICATE", "GeometryRatio": "GEOMETRY_RATIO"}[domain.splitPolicy]
			mergePolicy = {"AreaWeighted": "AREA_WEIGHTED", "DefaultValue": "DEFAULT", "SumValues": "SUM_VALUES"}[domain.mergePolicy]
			
			# Create the domain
			arcpy.management.CreateDomain(outGDB, name, description, fieldType, domainType, splitPolicy, mergePolicy)
			
			# Add Values
			if domainType == "CODED":
				for key, value in domain.codedValues.iteritems():
					arcpy.management.AddCodedValueToDomain(outGDB, name, key, value)
			
			else:
				arcpy.management.SetValueForRangeDomain(outGDB, name, domain.range[0], domain.range[1])
			
			arcpy.AddMessage("Cloned Domain {0}".format(domainName))
	
	return



def cloneRelationshipClass(desc, outGDB):
	'''Clone a relationship class (all properties)'''
	success = True
	name = desc.name.split(".")[-1]
	
	# Derive origin/destination tables paths for the output GDB
	originTableName = desc.originClassNames[0].split(".")[-1]
	originTable = "{0}\\{1}".format(outGDB, originTableName)
	
	destinTableName = desc.destinationClassNames[0].split(".")[-1]
	destinTable = "{0}\\{1}".format(outGDB, destinTableName)
	
	# Ensure origin/destination tables exists in output GDB
	if not arcpy.Exists(originTable):
		arcpy.AddError("Can't clone {0} as the {1} origin table is missing".format(name, originTableName))
		success = False
	
	elif not arcpy.Exists(destinTable):
		arcpy.AddError("Can't clone {0} as the {1} destination table is missing".format(name, destinTableName))
		success = False
	
	else:
		# Translate properties to parameters
		path_name = "{0}\\{1}".format(outGDB, name)
		relType = "COMPOSITE" if desc.isComposite else "SIMPLE"
		fLabel = desc.forwardPathLabel
		bLabel = desc.backwardPathLabel
		msg_dir = {"None": "NONE", "Forward": "FORWARD", "Backward": "BACK", "Both": "BOTH"}[desc.notification]
		cardinality = {"OneToOne": "ONE_TO_ONE", "OneToMany": "ONE_TO_MANY", "ManyToMany": "MANY_TO_MANY"}[desc.cardinality]
		attributed = "ATTRIBUTED" if desc.isAttributed else "NONE"
		originKeyPrim = desc.originClassKeys[0][0]
		originKeyFore = desc.originClassKeys[1][0]
		
		if len(desc.destinationClassKeys) > 0:
			destinKeyPrim = desc.destinationClassKeys[0][0]
			destinKeyFore = desc.destinationClassKeys[1][0]
		else:
			destinKeyPrim = None
			destinKeyFore = None
		
		# If attributed, copy the intermediate table while creating rel. class
		if desc.isAttributed:
			fields = [e.name for e in desc.fields]
			table = arcpy.CreateTable_management("in_memory", "relClass", "{0}\\{1}".format(desc.path, desc.name))
			arcpy.TableToRelationshipClass_management(originTable, destinTable, path_name, relType, fLabel, bLabel, msg_dir, cardinality, table, fields, originKeyPrim, originKeyFore, destinKeyPrim, destinKeyFore)
			arcpy.Delete_management(table)
		
		# If not attributed, create a simple relationship class
		else:
			arcpy.CreateRelationshipClass_management(originTable, destinTable, path_name, relType, fLabel, bLabel, msg_dir, cardinality, attributed, originKeyPrim, originKeyFore, destinKeyPrim, destinKeyFore)
		
		# Check for relationship rules (which are not copied by this tool)
		if len(desc.relationshipRules) > 0:
			arcpy.AddWarning("The {0} relationship class was cloned, but relationship rules could not be copied over".format(name))
		else:
			arcpy.AddMessage("Cloned Relationship Class {0}".format(name))
	
	return success



##UTILITIES########################################################################################

def existsOrReplace(outGDB, name, overwrite):
	'''Check whether dataset exists, and delete if overwriting'''
	dataset = "{0}\\{1}".format(outGDB,name)
	continueCloning = True
	
	# Check for dataset existence
	if arcpy.Exists(dataset):
		
		# If overwriting enabled, delete it, otherwise stop cloning
		if overwrite:
			try:
				arcpy.Delete_management(dataset)
			except Exception:
				arcpy.AddError("Could not delete {0}. Make sure it isn't locked. Dataset not cloned.".format(dataset))
				continueCloning = False
		else:
			continueCloning = False
			arcpy.AddWarning("Could not clone {0} as it already exists in output geodatabase.".format(dataset))
	
	return continueCloning



##MAIN EXECUTION CODE##############################################################################
if __name__ == "__main__":
	#Execute when running outside Python Toolbox
	
	# Attempt to retrieve parameters from normal toolbox tool
	datasetsParam = arcpy.GetParameterAsText(0)
	outGDBParam = arcpy.GetParameterAsText(1)
	overwriteParam = arcpy.GetParameterAsText(2).lower() == "true"
	
	# Process the attributes
	if datasetsParam is not None:
		datasetListParam = [x[1:-1] for x in datasetsParam.split(";")]
	
	# If none provided through parameters, fall-back to in-code parameters
	else:
		datasetListParam = params["datasets"]
		outGDBParamParam = params["outGDB"]
		overwriteParam = params["overwrite"]
	
	# Run the processing
	execute(datasetListParam, outGDBParam, overwriteParam)
