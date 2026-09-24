<link rel="stylesheet" href="../../../css/taxii.css" />

# TAXII 2.2 Proposal: Aggregate Collection

This proposal addresses

* (https://github.com/oasis-tcs/cti-taxii2/issues/120) - Provide aggregate collections for consumers to read data instead of having to search individual collections.

## Goals

1. Add a new type of collection that is read-only and which provides data from other collections.
2. Ensure that TAXII clients can programmatically determine that it is safe to only pull from aggregate collections and determine what data they will be receiving from these.
3. Ensure that security controls can be correctly applied to the aggregate collections.

## Non-Goals

1. Creating entirely new API Endpoints for TAXII
2. Changing how TAXII filter or TAXII query function
3. Mandate that TAXII servers MUST support aggregate collections
4. Introduce backward breaking changes for TAXII Server or Clients

## Summary of Proposal

Update the collection definition to add the `aggregates` property.  It will also update section 5 TAXII API - Collections to include the following:

 <hr style="height:2px;border-width:0;color:gray;background-color:gray"> 

Having read access to a TAXII Collection does not guarentee read access to all content within the TAXII Collection as servers may apply additional access controls to specific objects. TAXII collections **MAY** store duplicative content and can communicate this to TAXII Clients to ensure queries can be performed efficiently.

When an aggregate Collection contains the same object version from multiple underlying Collections, the object version **MUST** be treated as a single object version within the aggregate Collection. When multiple versions of the same STIX object are present across the underlying Collections, the versions MUST be treated according to the normal STIX versioning rules.

<hr style="height:2px;border-width:0;color:gray;background-color:gray"> 

The following table provides a summary of the Endpoints (URLs and HTTP Methods) defined by TAXII
and the Resources they operate on.

This will cause it to appear as:

<table border="1" cellspacing="0" cellpadding="6" width="100%">
  <tr>
    <th><span class="taxiitr">Property Name</span></th>
    <th><span class="taxiitr">Type</span></th>
    <th><span class="taxiitr">Description</span></th>
  </tr>
  <tr>
    <td><strong>id</strong> (required)</td>
    <td><span class="taxiitype">identifier</span></td>
    <td>The <strong>id</strong> property universally and uniquely identifies this Collection. It is used in the Get Collection Endpoint (see section <a href="#get-a-collection">5.2</a>) as the <strong>{id}</strong> parameter to retrieve the Collection.</td>
  </tr>
  <tr>
    <td><strong>title</strong> (required)</td>
    <td><span class="taxiitype">string</span></td>
    <td>A human readable plain text title used to identify this Collection.</td>
  </tr>
  <tr>
    <td><strong>description</strong> (optional)</td>
    <td><span class="taxiitype">string</span></td>
    <td>A human readable plain text description for this Collection.</td>
  </tr>
  <tr>
    <td><strong>alias</strong> (optional)</td>
    <td><span class="taxiitype">string</span></td>
    <td>A human readable collection name that can be used on systems to alias a collection ID. This could be used by organizations that want to preconfigure a known collection of data, regardless of the underlying collection ID that is configured on a specific implementations.<br><br>If defined, the alias <strong>MUST</strong> be unique within a single api-root on a single TAXII server. There is no guarantee that an alias is globally unique across api-roots or TAXII server instances.<br><br><br>Example: /{api-root}/collections/critical-high-value-indicators/</td>
  </tr>
  <tr>
    <td><strong>aggregates</strong> (optional)</td>
    <td><span class="taxiitype">list</span> of type <span class="taxiitype">string</span></td>
    <td><p>A list of collections aggregated within this collection for the user performing the query. Each entry in this list must follow one of the following formats:</p>
    <ol>
    <li><span class="taxiiliteral">*</span> - all non-aggregate collections across the current API root are included.</li>
    <li><strong>{id}</strong> - the listed collection in the current API root is included. This cannot reference an aggregate collection.</li>
    <li><span class="taxiiliteral">*</span>/<span class="taxiiliteral">*</span> - all non-aggregate collections across all API roots are included.</li>
    <li><strong>{api-root}</strong>/<span class="taxiiliteral">*</span> - all non-aggregate collections across the listed API root are included.</li>
    <li><strong>{api-root}</strong>/<strong>{id}</strong> - the listed collection in the listed API root is included. This cannot reference an aggregate collection.</li>
    </ol>
    <p>If this property is defined, the collection is an aggregate collection and <span class="taxiitype">can_write</span> MUST be <span class="taxiiliteral">false</span>.</p>
    <p>Aggregate collections <strong>MUST NOT</strong> provide TAXII Clients access to content that the clients are not otherwise authorized to access. All content in aggregate collections <strong>MUST</strong> be present in one or more of the referenced collections.</p>
    </td>
  </tr>
  <tr>
    <td><strong>can_read</strong> (required)</td>
    <td><span class="taxiitype">boolean</span></td>
    <td>Indicates if the requester can read (i.e., GET) objects from this Collection. If <span class="taxiiliteral">true</span>, users are allowed to access the <strong>Get Objects</strong>, <strong>Get an Object</strong>, or <strong>Get Object Manifests</strong> endpoints for this Collection. If <span class="taxiiliteral">false</span>, users are not allowed to access these endpoints.</td>
  </tr>
  <tr>
    <td><strong>can_write </strong>(required)</td>
    <td><span class="taxiitype">boolean</span></td>
    <td>Indicates if the requester can write (i.e., POST) objects to this Collection. If <span class="taxiiliteral">true</span>, users are allowed to access the <strong>Add Objects</strong> endpoint for this Collection. If <span class="taxiiliteral">false</span>, users are not allowed to access this endpoint.</td>
  </tr>
  <tr>
    <td><strong>media_types </strong>(optional)</td>
    <td><span class="taxiitype">list</span> of type <span class="taxiitype">string</span></td>
    <td>A list of supported media types for Objects in this Collection. Absence of this property is equivalent to a single-value list containing  "<code>application/stix+json"</code>. This list <strong>MUST</strong> describe all media types that the Collection can store.</td>
  </tr>
</table>

